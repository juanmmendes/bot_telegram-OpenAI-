from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from requests import RequestException


class CurrencyService:
    """Fetches currency information from AwesomeAPI and formats human-readable output."""

    PTAX_BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata"

    def __init__(self, request_timeout: int = 20, ptax_max_fallback_days: int = 7) -> None:
        self.request_timeout = request_timeout
        self.ptax_max_fallback_days = max(0, ptax_max_fallback_days)

    def fetch_currency_snapshot(self, codes: Sequence[str]) -> Optional[str]:
        if not codes:
            return None

        pairs = ",".join(f"{code}-BRL" for code in codes)
        url = f"https://economia.awesomeapi.com.br/json/last/{pairs}"

        response = requests.get(url, timeout=self.request_timeout)
        response.raise_for_status()
        payload: Dict[str, Dict[str, str]] = response.json()

        lines: List[str] = []
        timestamp_display: Optional[str] = None

        for code in codes:
            info = payload.get(f"{code}BRL")
            if not isinstance(info, dict):
                continue

            price_text = self._safe_number(info.get("bid") or info.get("ask"))
            variation_text = self._format_variation(info.get("pctChange"))
            update_reference = info.get("create_date") or info.get("timestamp")

            if update_reference and not timestamp_display:
                timestamp_display = self._format_timestamp(update_reference)

            lines.append(f"- {code}/BRL: {price_text}{variation_text}")

        if not lines:
            return None

        header = "[Contexto em tempo real]\nCotacoes consultadas via AwesomeAPI:"
        body = "\n".join(lines)
        if timestamp_display:
            return f"{header}\n{body}\nDados consultados em {timestamp_display}."
        return f"{header}\n{body}"

    def fetch_historical_snapshot(
        self,
        codes: Sequence[str],
        target_date: date | datetime,
    ) -> Optional[str]:
        normalized_codes = self._normalize_codes(codes)
        if not normalized_codes:
            return None

        requested_date = self._ensure_date(target_date)
        requested_display = requested_date.strftime("%d/%m/%Y")

        lines: List[str] = []
        for code in normalized_codes:
            quote = self._fetch_ptax_quote(code, requested_date)
            if not quote:
                continue
            lines.append(self._format_ptax_line(code, quote, requested_date))

        if not lines:
            return None

        header = "[Contexto historico]\nCotacoes oficiais do Banco Central (PTAX)."
        body = "\n".join(lines)
        return f"{header}\nDados solicitados para {requested_display}:\n{body}"

    @staticmethod
    def _safe_number(value: Optional[object]) -> str:
        if value is None:
            return "-"
        try:
            number = float(str(value).replace(",", "."))
            return f"R$ {number:.4f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_variation(value: Optional[str]) -> str:
        if value is None:
            return ""
        try:
            number = float(str(value).replace(",", "."))
            return f" (variacao diaria: {number:+.2f}%)"
        except (TypeError, ValueError):
            return f" (variacao diaria: {value})"

    @staticmethod
    def _format_timestamp(value: object) -> str:
        text = str(value)
        if text.isdigit():
            try:
                dt = datetime.fromtimestamp(int(text))
                return dt.strftime("%d/%m/%Y %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                return text

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime("%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue
        return text

    def warmup(self, default_codes: Iterable[str]) -> None:
        """Optional helper that tries to warm the currency cache early."""
        try:
            self.fetch_currency_snapshot(list(default_codes))
        except RequestException:
            # Ignore warmup errors to avoid impacting bot startup
            return

    @staticmethod
    def _ensure_date(value: date | datetime) -> date:
        if isinstance(value, datetime):
            return value.date()
        return value

    @staticmethod
    def _normalize_codes(codes: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for code in codes:
            if not code:
                continue
            normalized_code = str(code).strip().upper()
            if normalized_code and normalized_code not in seen:
                normalized.append(normalized_code)
                seen.add(normalized_code)
        return normalized

    def _fetch_ptax_quote(self, code: str, requested_date: date) -> Optional[Dict[str, Any]]:
        current_reference = requested_date
        attempts = self.ptax_max_fallback_days + 1

        for _ in range(attempts):
            payload = self._query_ptax_endpoint(code, current_reference)
            if payload:
                sale = self._to_float(payload.get("cotacaoVenda"))
                buy = self._to_float(payload.get("cotacaoCompra"))
                timestamp = self._parse_ptax_datetime(payload.get("dataHoraCotacao"))
                return {
                    "sale": sale,
                    "buy": buy,
                    "timestamp": timestamp,
                    "reference_date": current_reference,
                }
            current_reference = current_reference - timedelta(days=1)

        return None

    def _query_ptax_endpoint(self, code: str, reference_date: date) -> Optional[Dict[str, Any]]:
        date_param = reference_date.strftime("%m-%d-%Y")
        if code == "USD":
            url = (
                f"{self.PTAX_BASE_URL}/CotacaoDolarDia(dataCotacao=@dataCotacao)"
                f"?@dataCotacao='{date_param}'&$format=json"
            )
        else:
            url = (
                f"{self.PTAX_BASE_URL}/CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
                f"?@moeda='{code}'&@dataInicial='{date_param}'&@dataFinalCotacao='{date_param}'"
                "&$top=1&$orderby=dataHoraCotacao%20desc&$format=json"
            )

        response = requests.get(url, timeout=self.request_timeout)
        response.raise_for_status()
        payload = response.json()
        values: List[Dict[str, Any]] = payload.get("value") or []
        if not values:
            return None

        if code == "USD":
            return values[0]

        return self._select_ptax_record(values)

    @staticmethod
    def _select_ptax_record(entries: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for entry in entries:
            tipo = (entry.get("tipoBoletim") or "").strip().lower()
            if tipo == "fechamento":
                return entry
        return entries[0] if entries else None

    @staticmethod
    def _parse_ptax_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        text = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    def _format_ptax_line(
        self,
        code: str,
        quote: Dict[str, Any],
        requested_date: date,
    ) -> str:
        sale_text = self._safe_number(quote.get("sale"))
        buy_float = quote.get("buy")
        buy_text = self._safe_number(buy_float) if buy_float is not None else ""

        line = f"- {code}/BRL: venda {sale_text}"
        if buy_float is not None:
            line += f" | compra {buy_text}"

        timestamp: Optional[datetime] = quote.get("timestamp")
        reference_date = quote.get("reference_date")
        suffix_parts: List[str] = []

        if timestamp:
            suffix_parts.append(timestamp.strftime("%d/%m/%Y %H:%M"))
        elif isinstance(reference_date, date):
            suffix_parts.append(reference_date.strftime("%d/%m/%Y"))

        if isinstance(reference_date, date) and reference_date != requested_date:
            suffix_parts.append(
                f"ultimo registro antes de {requested_date.strftime('%d/%m/%Y')}"
            )

        if suffix_parts:
            line += " — " + " | ".join(suffix_parts)

        return line

from datetime import datetime

from stock_research.domain.models import Evidence


class EvidenceService:
    def validate_and_deduplicate(self, evidence: list[Evidence]) -> list[Evidence]:
        retained_by_url: dict[str, Evidence] = {}
        for item in evidence:
            key = str(item.url).split("#", maxsplit=1)[0]
            current = retained_by_url.get(key)
            if current is None or self._is_preferred(item, current):
                retained_by_url[key] = item
        return list(retained_by_url.values())

    @staticmethod
    def _is_preferred(candidate: Evidence, current: Evidence) -> bool:
        if candidate.credibility != current.credibility:
            return candidate.credibility > current.credibility

        candidate_published = EvidenceService._timestamp(candidate.published_at)
        current_published = EvidenceService._timestamp(current.published_at)
        if candidate_published != current_published:
            return candidate_published > current_published

        return EvidenceService._timestamp(candidate.retrieved_at) > EvidenceService._timestamp(
            current.retrieved_at
        )

    @staticmethod
    def _timestamp(value: datetime | None) -> float:
        return float("-inf") if value is None else value.timestamp()

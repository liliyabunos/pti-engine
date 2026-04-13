from perfume_trend_sdk.core.models.content import CanonicalContentItem

KEYWORDS = [
    "Dior",
    "Tom Ford",
    "Creed",
    "Baccarat Rouge 540",
    "Oud Wood",
    "Sauvage",
]


class PerfumeMentionExtractor:
    def extract(self, item: CanonicalContentItem) -> dict:
        text = " ".join(filter(None, [item.title, item.text_content]))
        mentions = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
        return {
            "item_id": item.id,
            "perfume_mentions": mentions,
        }

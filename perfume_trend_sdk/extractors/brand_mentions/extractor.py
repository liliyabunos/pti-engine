from perfume_trend_sdk.core.models.content import CanonicalContentItem

BRANDS = [
    "Dior",
    "Tom Ford",
    "Creed",
    "Chanel",
    "Maison Francis Kurkdjian",
    "Parfums de Marly",
]


class BrandMentionExtractor:
    def extract(self, item: CanonicalContentItem) -> dict:
        text = " ".join(filter(None, [item.title, item.text_content]))
        mentions = [brand for brand in BRANDS if brand.lower() in text.lower()]
        return {
            "item_id": item.id,
            "brand_mentions": mentions,
        }

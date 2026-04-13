class MockYouTubeConnector:
    name = "youtube"

    def validate_config(self, config: dict) -> None:
        pass

    def fetch(self) -> dict:
        return {
            "items": [
                {"id": "yt1", "title": "Top 5 perfumes 2026", "text": "Chanel No5, Dior Sauvage and Tom Ford are dominating this season."},
                {"id": "yt2", "title": "Best luxury fragrances", "text": "Creed Aventus and MFK Baccarat Rouge 540 are worth every penny."},
            ]
        }

import logging


class AstrBotConfig(dict):
    """形状镜像 astrbot.api.AstrBotConfig（dict 语义 + save_config）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = False

    def save_config(self) -> None:
        self.saved = True


logger = logging.getLogger("astrbot-stub")

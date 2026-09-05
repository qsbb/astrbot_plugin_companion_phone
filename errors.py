from __future__ import annotations


class PhoneError(Exception):
    """业务异常：code 对外暴露给模型，message 为可直接展示的中文说明。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def public_dict(self, action: str = "") -> dict:
        payload = {
            "status": "error",
            "error_code": self.code,
            "message": self.message,
        }
        if action:
            payload["action"] = action
        return payload


# 语义分层别名：同一异常类型，避免循环导入
BackendError = PhoneError
DeviceError = PhoneError
SafetyError = PhoneError

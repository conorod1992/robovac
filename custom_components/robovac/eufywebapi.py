"""Original Work from here: Andre Borie https://gitlab.com/Rjevski/eufy-device-id-and-local-key-grabber"""

import requests

eufyheaders = {
    "User-Agent": "EufyHome-Android-2.4.0",
    "timezone": "Europe/London",
    "category": "Home",
    "token": "",
    "uid": "",
    "openudid": "sdk_gphone64_arm64",
    "clientType": "2",
    "language": "en",
    "country": "US",
    "Accept-Encoding": "gzip",
}

REQUEST_TIMEOUT = 10


class EufyLogon:
    def __init__(self, username, password):
        self.username = username
        self.password = password

    def get_user_info(self):
        login_url = "https://home-api.eufylife.com/v1/user/email/login"
        login_auth = {
            "client_Secret": "GQCpr9dSp3uQpsOMgJ4xQ",
            "client_id": "eufyhome-app",
            "email": self.username,
            "password": self.password,
        }

        try:
            headers = eufyheaders.copy()
            return requests.post(
                login_url,
                json=login_auth,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException:
            return None

    def get_user_settings(self, url, userid, token):
        setting_url = url + "/v1/user/setting"
        headers = eufyheaders.copy()
        headers["token"] = token
        headers["id"] = userid
        try:
            return requests.request(
                "GET",
                setting_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException:
            return None

    def get_device_info(self, url, userid, token):
        device_url = url + "/v1/device/list/devices-and-groups"
        headers = eufyheaders.copy()
        headers["token"] = token
        headers["id"] = userid
        try:
            return requests.request(
                "GET",
                device_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException:
            return None

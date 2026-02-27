# -*- coding: utf8 -*-
import math, traceback, uuid, json, random, re, time, os, pytz, requests
from datetime import datetime
from util.aes_help import encrypt_data, decrypt_data
import util.zepp_helper as zeppHelper
import util.push_util as push_util

def get_int_value_default(_config, _key, default):
    _config.setdefault(_key, default)
    return int(_config.get(_key))

def get_beijing_time():
    return datetime.now().astimezone(pytz.timezone('Asia/Shanghai'))

def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

def get_time():
    return "%.0f" % (get_beijing_time().timestamp() * 1000)

# --- 新增：使用稳定且免密的 Open-Meteo 接口精准获取合肥天气 ---
def get_hefei_weather_code():
    try:
        # 合肥的经纬度: 纬度 31.8639, 经度 117.2808
        url = "https://api.open-meteo.com/v1/forecast?latitude=31.8639&longitude=117.2808&current=weather_code"
        # 增加超时时间到 10 秒，确保网络波动时也能抓到
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # 返回 WMO 天气代码
            return data.get("current", {}).get("weather_code", -1)
        return -1
    except:
        return -1

# --- 修改：根据国际气象代码动态生成区间 ---
def get_min_max_by_time():
    config_min = get_int_value_default(config, 'MIN_STEP', 12000)
    config_max = get_int_value_default(config, 'MAX_STEP', 18000)
    
    w_code = get_hefei_weather_code()
    weather_desc = "未知"

    # WMO 国际天气代码解析 (WMO code 4677)
    if w_code in [0, 1, 2]:
        # 0: 晴空, 1: 主要是晴天, 2: 局部多云
        base_min, base_max = 15000, 18000
        desc = "晴朗" if w_code == 0 else "多云"
        weather_desc = f"好天气({desc})"
    elif w_code in [3, 45, 48]:
        # 3: 阴天, 45/48: 雾霾
        base_min, base_max = 11000, 14000
        desc = "阴天" if w_code == 3 else "雾霾"
        weather_desc = f"阴雾天({desc})"
    elif w_code >= 50:
        # 50以上全是各种雨雪恶劣天气 (毛毛雨、阵雨、大雪、雷暴等)
        base_min, base_max = 10000, 12500
        if 50 <= w_code <= 69 or 80 <= w_code <= 82:
            desc = "降雨"
        elif 70 <= w_code <= 79 or 85 <= w_code <= 86:
            desc = "降雪"
        elif w_code >= 95:
            desc = "雷暴"
        else:
            desc = "恶劣天气"
        weather_desc = f"雨雪天({desc})"
    else:
        # 获取失败或无法识别时，使用配置的默认值
        base_min, base_max = config_min, config_max
        weather_desc = "获取天气超时，使用默认配置"

    time_bj = get_beijing_time()
    time_rate = min((time_bj.hour * 60 + time_bj.minute) / (22 * 60), 1)
    return int(time_rate * base_min), int(time_rate * base_max), weather_desc

class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user = str(_user) if str(_user).startswith("+86") or "@" in str(_user) else "+86"+str(_user)
        self.password = str(_passwd)
        self.is_phone = self.user.startswith("+86")
        self.device_id = str(uuid.uuid4())
        self.user_id, self.invalid, self.log_str = None, False, ""

    def login(self):
        user_info = user_tokens.get(self.user)
        if user_info:
            self.user_id = user_info.get("user_id")
            self.device_id = user_info.get("device_id", self.device_id)
            ok, _ = zeppHelper.check_app_token(user_info.get("app_token"))
            if ok:
                self.log_str += "使用加密Token成功\n"
                return user_info.get("app_token")
        
        # 重新登录逻辑
        token, msg = zeppHelper.login_access_token(self.user, self.password)
        if not token: return None
        lt, at, uid, _ = zeppHelper.grant_login_tokens(token, self.device_id, self.is_phone)
        if not lt: return None
        
        user_tokens[self.user] = {"access_token":token, "login_token":lt, "app_token":at, "

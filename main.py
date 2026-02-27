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

# --- 新增：获取合肥实时天气 ---
def get_hefei_weather():
    try:
        # 获取合肥英文天气简码，超时设置5秒防阻塞
        resp = requests.get("https://wttr.in/Hefei?format=%C", timeout=5)
        if resp.status_code == 200:
            return resp.text.strip().lower()
        return "unknown"
    except:
        return "unknown"

# --- 修改：根据天气动态生成区间 ---
def get_min_max_by_time():
    config_min = get_int_value_default(config, 'MIN_STEP', 12000)
    config_max = get_int_value_default(config, 'MAX_STEP', 18000)
    
    weather = get_hefei_weather()
    weather_desc = "未知"

    # 根据天气关键词调整基础步数范围
    if any(word in weather for word in ['sun', 'clear', 'cloud', 'fair']):
        base_min, base_max = 15000, 18000
        weather_desc = f"好天气({weather})"
    elif any(word in weather for word in ['rain', 'snow', 'shower', 'sleet', 'thunder', 'storm', 'drizzle']):
        base_min, base_max = 10000, 12500
        weather_desc = f"雨雪天({weather})"
    elif any(word in weather for word in ['overcast', 'mist', 'fog', 'haze']):
        base_min, base_max = 11000, 14000
        weather_desc = f"阴雾天({weather})"
    else:
        # 获取失败或无法识别时，使用配置的默认值
        base_min, base_max = config_min, config_max
        if weather != "unknown":
            weather_desc = f"其他天气({weather})"
        else:
            weather_desc = "获取天气失败，使用默认配置"

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
        
        user_tokens[self.user] = {"access_token":token, "login_token":lt, "app_token":at, "user_id":uid, "device_id":self.device_id}
        self.user_id = uid
        return at

    def run(self, min_s, max_s):
        at = self.login()
        if not at: return "登录失败", False
        
        # --- 吉利步数核心逻辑 ---
        step_val = 0
        for _ in range(200): # 尝试200次找最吉利的
            tmp = random.randint(min_s, max_s)
            s = str(tmp)
            if '4' not in s:
                step_val = tmp
                if any(d in s for d in '689'): break # 只要含689且没4，立即锁定
        if step_val == 0: step_val = random.randint(min_s, max_s) # 彻底没辙时的保底
        
        step = str(step_val)
        ok, msg = zeppHelper.post_fake_brand_data(step, at, self.user_id)
        return f"修改步数({step}) [{msg}]", ok

def run_single(total, idx, u, p, min_step, max_step, weather_desc):
    print(f"[{format_now()}] [{idx+1}/{total}] 账号: {u[:3]}****{u[-4:]}")
    try:
        runner = MiMotionRunner(u, p)
        runner.log_str += f"天气: {weather_desc}, 目标区间: {min_step}~{max_step}\n"
        msg, ok = runner.run(min_step, max_step)
        print(runner.log_str + msg)
        return {"user":u, "success":ok, "msg":msg}
    except:
        print(traceback.format_exc()); return {"user":u, "success":False, "msg":"出错"}

if __name__ == "__main__":
    if "CONFIG" not in os.environ: exit(1)
    config = json.loads(os.environ.get("CONFIG"))
    aes_key = os.environ.get("AES_KEY", "").encode('utf-8')
    encrypt_support = len(aes_key) == 16
    
    # 读取Token
    user_tokens = {}
    if encrypt_support and os.path.exists("encrypted_tokens.data"):
        try:
            with open("encrypted_tokens.data", 'rb') as f:
                user_tokens = json.loads(decrypt_data(f.read(), aes_key, None).decode('utf-8'))
        except: pass

    users, pwds = config.get('USER').split('#'), config.get('PWD').split('#')
    
    # 获取天气和步数区间
    min_step, max_step, weather_desc = get_min_max_by_time()
    print(f"当前合肥天气判定: {weather_desc}")
    
    results = [run_single(len(users), i, u, p, min_step, max_step, weather_desc) for i, (u, p) in enumerate(zip(users, pwds))]

    # 保存Token
    if encrypt_support:
        with open("encrypted_tokens.data", 'wb') as f:
            f.write(encrypt_data(json.dumps(user_tokens).encode("utf-8"), aes_key, None))
    
    # 将天气情况也加入到推送摘要中
    summary = f"\n合肥天气: {weather_desc}\n总数{len(users)}，成功：{sum(1 for r in results if r['success'])}"
    print(summary)
    push_util.push_results(results, summary, push_util.PushConfig(
        config.get('PUSH_PLUS_TOKEN'), config.get('PUSH_PLUS_HOUR'), 30,
        config.get('PUSH_WECHAT_WEBHOOK_KEY'), config.get('TELEGRAM_BOT_TOKEN'), config.get('TELEGRAM_CHAT_ID')
    ))

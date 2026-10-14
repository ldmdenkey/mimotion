# -*- coding: utf8 -*-
import traceback, uuid, json, random, os, pytz
from datetime import datetime
from util.aes_help import encrypt_data, decrypt_data
import util.zepp_helper as zeppHelper
import util.push_util as push_util

def get_beijing_time():
    return datetime.now().astimezone(pytz.timezone('Asia/Shanghai'))

def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

# 获取时间戳（毫秒），用于记录 token 获取时间
def get_time():
    current_time = get_beijing_time()
    return "%.0f" % (current_time.timestamp() * 1000)

def get_min_max_by_time(config):
    time_bj = get_beijing_time()
    # 如果是晚上 18:00 之后运行（专门对应 21:00 的晚间任务）
    if time_bj.hour >= 18:
        min_s = int(config.get('MIN_STEP', 12000))
        max_s = int(config.get('MAX_STEP', 18000))
        return min_s, max_s, "夜间满额模式"
    else:
        # 如果是白天运行（专门对应 15:00 的下午任务，或你白天手动触发），使用保底数据
        return 8000, 11000, "下午保底模式"

class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user = str(_user) if str(_user).startswith("+86") or "@" in str(_user) else "+86"+str(_user)
        self.password = str(_passwd)
        self.is_phone = self.user.startswith("+86")
        self.device_id = str(uuid.uuid4())
        self.user_id, self.log_str = None, ""

    def login(self):
        user_token_info = user_tokens.get(self.user)
        if user_token_info is not None:
            access_token = user_token_info.get("access_token")
            login_token = user_token_info.get("login_token")
            app_token = user_token_info.get("app_token")
            self.device_id = user_token_info.get("device_id")
            self.user_id = user_token_info.get("user_id")
            if self.device_id is None:
                self.device_id = str(uuid.uuid4())
                user_token_info["device_id"] = self.device_id
            ok, msg = zeppHelper.check_app_token(app_token)
            if ok:
                self.log_str += "使用加密保存的app_token\n"
                return app_token
            else:
                self.log_str += f"app_token失效 重新获取 last grant time: {user_token_info.get('app_token_time')}\n"
                # 检查login_token是否可用
                app_token, msg = zeppHelper.grant_app_token(login_token)
                if app_token is None:
                    self.log_str += f"login_token 失效 重新获取 last grant time: {user_token_info.get('login_token_time')}\n"
                    login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id, self.is_phone)
                    if login_token is None:
                        self.log_str += f"access_token 已失效：{msg} last grant time:{user_token_info.get('access_token_time')}\n"
                    else:
                        user_token_info["login_token"] = login_token
                        user_token_info["app_token"] = app_token
                        user_token_info["user_id"] = user_id
                        user_token_info["login_token_time"] = get_time()
                        user_token_info["app_token_time"] = get_time()
                        self.user_id = user_id
                        return app_token
                else:
                    self.log_str += "重新获取app_token成功\n"
                    user_token_info["app_token"] = app_token
                    user_token_info["app_token_time"] = get_time()
                    return app_token

        # access_token 失效 或者没有保存加密数据，完整重新登录
        access_token, msg = zeppHelper.login_access_token(self.user, self.password)
        if access_token is None:
            self.log_str += "登录获取accessToken失败：%s" % msg
            return None
        login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id, self.is_phone)
        if login_token is None:
            self.log_str += f"登录提取的 access_token 无效：{msg}"
            return None

        user_token_info = dict()
        user_token_info["access_token"] = access_token
        user_token_info["login_token"] = login_token
        user_token_info["app_token"] = app_token
        user_token_info["user_id"] = user_id
        # 记录token获取时间
        user_token_info["access_token_time"] = get_time()
        user_token_info["login_token_time"] = get_time()
        user_token_info["app_token_time"] = get_time()
        user_token_info["device_id"] = self.device_id
        user_tokens[self.user] = user_token_info
        self.user_id = user_id
        return app_token

    def run(self, min_s, max_s):
        at = self.login()
        if not at: return "登录失败", False
        
        # --- 吉利步数核心逻辑（无4，且含6/8/9） ---
        step_val = 0
        for _ in range(200): # 尝试200次找最吉利的
            tmp = random.randint(min_s, max_s)
            s = str(tmp)
            if '4' not in s:
                step_val = tmp
                if any(d in s for d in '689'): break # 只要含689且没4，立即锁定
        if step_val == 0: step_val = random.randint(min_s, max_s) # 彻底没辙时的保底
        
        step = str(step_val)
        # 查询账号真实绑定的手环设备ID（华米已校验设备ID，硬编码假ID可能被拒）
        user_token_info = user_tokens.get(self.user, {})
        bound_device_id = user_token_info.get("bound_device_id")
        if not bound_device_id and self.user_id:
            bound_device_id = zeppHelper.get_user_device_id(at, self.user_id)
            if bound_device_id:
                user_token_info["bound_device_id"] = bound_device_id
                user_tokens[self.user] = user_token_info
                self.log_str += f"查找到已绑定设备ID: {bound_device_id}\n"
        ok, msg = zeppHelper.post_fake_brand_data(step, at, self.user_id, device_id=bound_device_id)
        return f"修改步数({step}) [{msg}]", ok

def run_single(total, idx, u, p, min_step, max_step, mode_desc):
    print(f"[{format_now()}] [{idx+1}/{total}] 账号: {u[:3]}****{u[-4:]}")
    try:
        runner = MiMotionRunner(u, p)
        runner.log_str += f"当前策略: {mode_desc}, 目标区间: {min_step}~{max_step}\n"
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
    
    # 获取根据时间动态生成的区间
    min_step, max_step, mode_desc = get_min_max_by_time(config)
    
    results = [run_single(len(users), i, u, p, min_step, max_step, mode_desc) for i, (u, p) in enumerate(zip(users, pwds))]

    # 保存Token
    if encrypt_support:
        with open("encrypted_tokens.data", 'wb') as f:
            f.write(encrypt_data(json.dumps(user_tokens).encode("utf-8"), aes_key, None))
    
    summary = f"\n总数{len(users)}，成功：{sum(1 for r in results if r['success'])}"
    print(summary)
    push_util.push_results(results, summary, push_util.PushConfig(
        config.get('PUSH_PLUS_TOKEN'), config.get('PUSH_PLUS_HOUR'), 30,
        config.get('PUSH_WECHAT_WEBHOOK_KEY'), config.get('TELEGRAM_BOT_TOKEN'), config.get('TELEGRAM_CHAT_ID')
    ))

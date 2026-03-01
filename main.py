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

class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user = str(_user) if str(_user).startswith("+86") or "@" in str(_user) else "+86"+str(_user)
        self.password = str(_passwd)
        self.is_phone = self.user.startswith("+86")
        self.device_id = str(uuid.uuid4())
        self.user_id, self.log_str = None, ""

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

def run_single(total, idx, u, p, min_step, max_step):
    print(f"[{format_now()}] [{idx+1}/{total}] 账号: {u[:3]}****{u[-4:]}")
    try:
        runner = MiMotionRunner(u, p)
        runner.log_str += f"目标区间: {min_step}~{max_step}\n"
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
    
    # 直接读取配置中的步数范围（去除时间折算，满额释放）
    min_step = int(config.get('MIN_STEP', 12000))
    max_step = int(config.get('MAX_STEP', 18000))
    
    results = [run_single(len(users), i, u, p, min_step, max_step) for i, (u, p) in enumerate(zip(users, pwds))]

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

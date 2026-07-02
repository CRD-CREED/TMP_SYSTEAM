from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pymysql
from pymysql.cursors import DictCursor
import time

app = Flask(__name__)
CORS(app)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'db': 'tpm_system',
    'charset': 'utf8mb4',
    'cursorclass': DictCursor
}

def get_conn():
    return pymysql.connect(**DB_CONFIG)

# ==================== 登录 ====================
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = "SELECT * FROM users WHERE username=%s AND password=%s AND role=%s"
            cur.execute(sql, (username, password, role))
            user = cur.fetchone()
    finally:
        conn.close()

    if not user:
        return jsonify({"code": 400, "msg": "账号、密码或角色不匹配"})

    return jsonify({
        "code": 200,
        "msg": "登录成功",
        "data": {
            "uid": user['uid'],
            "username": user['username'],
            "role": user['role'],
            "real_name": user['real_name']
        }
    })

# ==================== 注册（仅限操作员和维修员）====================
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    real_name = data.get("real_name", "").strip()
    role = data.get("role", "").strip()

    if not username or not password or not real_name:
        return jsonify({"code": 400, "msg": "账号、密码、真实姓名不能为空"})

    if role not in ("operator", "maintainer"):
        return jsonify({"code": 400, "msg": "只能注册操作员或维修员"})

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT uid FROM users WHERE username=%s", (username,))
            if cur.fetchone():
                return jsonify({"code": 400, "msg": "该账号已被注册"})

            sql = "INSERT INTO users (username, password, role, real_name) VALUES (%s, %s, %s, %s)"
            cur.execute(sql, (username, password, role, real_name))
            conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"code": 500, "msg": f"注册失败: {str(e)}"})
    finally:
        conn.close()

    return jsonify({"code": 200, "msg": "注册成功！请登录"})

# ==================== 设备列表 ====================
@app.route("/api/devices")
def api_devices():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM devices")
            devices = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"code": 200, "data": devices})

# ==================== 提交点检 ====================
@app.route("/api/inspection/add", methods=["POST"])
def api_add_inspection():
    data = request.get_json()
    device_id = data.get("device_id")
    user_id = data.get("user_id")
    content = data.get("content")
    issue = data.get("issue", "")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO inspections (device_id, user_id, check_content, issue)
            VALUES (%s, %s, %s, %s)
            """
            cur.execute(sql, (device_id, user_id, content, issue))
            conn.commit()
    finally:
        conn.close()

    return jsonify({"code": 200, "msg": "点检提交成功"})

# ==================== 提交报修 ====================
@app.route("/api/repair/add", methods=["POST"])
def api_add_repair():
    data = request.get_json()
    device_id = data.get("device_id")
    user_id = data.get("user_id")
    desc = data.get("description")
    urgency = data.get("urgency")

    work_order = "R" + time.strftime("%Y%m%d%H%M%S")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO repairs (work_order, device_id, user_id, description, urgency)
            VALUES (%s, %s, %s, %s, %s)
            """
            cur.execute(sql, (work_order, device_id, user_id, desc, urgency))
            cur.execute("UPDATE devices SET status='故障' WHERE id=%s", (device_id,))
            conn.commit()
    finally:
        conn.close()

    return jsonify({"code": 200, "msg": f"报修成功，工单号：{work_order}"})

# ==================== 我的点检记录 ====================
@app.route("/api/inspection/my/<int:uid>")
def api_my_inspection(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
            SELECT i.*, d.device_name
            FROM inspections i
            LEFT JOIN devices d ON i.device_id = d.id
            WHERE i.user_id = %s
            ORDER BY i.create_time DESC
            """
            cur.execute(sql, (uid,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"code": 200, "data": rows})

# ==================== 我的报修记录 ====================
@app.route("/api/repair/my/<int:uid>")
def api_my_repair(uid):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
            SELECT r.*, d.device_name
            FROM repairs r
            LEFT JOIN devices d ON r.device_id = d.id
            WHERE r.user_id = %s
            ORDER BY r.create_time DESC
            """
            cur.execute(sql, (uid,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"code": 200, "data": rows})

# ==================== 全部工单（无角色拦截，但前端按角色显示按钮）====================
@app.route("/api/repair/all")
def api_all_repair():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sql = """
            SELECT r.*, d.device_name, u.real_name
            FROM repairs r
            LEFT JOIN devices d ON r.device_id = d.id
            LEFT JOIN users u ON r.user_id = u.uid
            ORDER BY r.status, r.create_time DESC
            """
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify({"code": 200, "data": rows})

# ==================== 更新工单状态（仅维修员和管理员）====================
@app.route("/api/repair/update", methods=["POST"])
def api_update_repair():
    data = request.get_json()
    wo = data.get("work_order")
    status = data.get("status")
    role = data.get("role", "")   # 前端传入当前用户的角色

    # 权限校验：只允许维修员或管理员操作
    if role not in ("maintainer", "admin"):
        return jsonify({"code": 403, "msg": "无权限，仅维修员或管理员可操作"})

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE repairs SET status=%s WHERE work_order=%s", (status, wo))
            if status == "处理中":
                cur.execute("""
                    UPDATE devices SET status='维修中'
                    WHERE id = (SELECT device_id FROM repairs WHERE work_order=%s)
                """, (wo,))
            elif status == "已完成":
                cur.execute("""
                    UPDATE devices SET status='正常'
                    WHERE id = (SELECT device_id FROM repairs WHERE work_order=%s)
                """, (wo,))
            conn.commit()
    finally:
        conn.close()
    return jsonify({"code": 200, "msg": "状态已更新"})

# ==================== 前端页面 ====================
@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/<path:page>")
def frontend(page):
    return send_from_directory("frontend", page)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
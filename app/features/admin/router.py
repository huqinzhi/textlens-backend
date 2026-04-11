"""
管理员路由模块

提供管理员页面和用户管理API接口。
"""
from fastapi import APIRouter, Depends, HTTPException, status, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.db.session import get_db
from app.db.models.user import User
from app.features.admin.service import AdminService
from app.core.security import create_access_token
from app.core.exceptions import AuthenticationError, NotFoundError, ValidationError


class UpdateUserRequest(BaseModel):
    """更新用户请求模型"""
    username: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None


class AdjustCreditsRequest(BaseModel):
    """调整积分请求模型"""
    credits: int
    reason: Optional[str] = ""


router = APIRouter()
security = HTTPBearer()


def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    获取当前管理员用户的依赖函数

    [credentials] HTTP Bearer Token 凭证
    [db] 数据库会话对象
    返回 当前管理员用户 ORM 对象
    """
    from app.core.security import verify_access_token

    token = credentials.credentials
    payload = verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.is_admin == True,
    ).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


@router.get("/admin/login", response_class=HTMLResponse, tags=["管理员"])
async def admin_login_page():
    """
    返回管理员登录页面
    """
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TextLens 管理后台</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 400px; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; font-size: 24px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; color: #555; font-weight: 500; }
        input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; transition: border-color 0.3s; }
        input:focus { outline: none; border-color: #667eea; }
        button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 6px; font-size: 16px; font-weight: 600; cursor: pointer; transition: transform 0.2s; }
        button:hover { transform: translateY(-2px); }
        button:active { transform: translateY(0); }
        .error { color: #e74c3c; text-align: center; margin-top: 15px; display: none; }
        .footer { text-align: center; margin-top: 20px; color: #999; font-size: 12px; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>TextLens 管理后台</h1>
        <form id="loginForm">
            <div class="form-group">
                <label>管理员邮箱</label>
                <input type="email" id="email" required placeholder="admin@example.com">
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="password" required placeholder="输入密码">
            </div>
            <button type="submit">登 录</button>
            <div class="error" id="error"></div>
        </form>
        <div class="footer">仅限管理员访问</div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;
            try {
                const resp = await fetch('/api/v1/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password})
                });
                const data = await resp.json();
                if (resp.ok) {
                    localStorage.setItem('admin_token', data.access_token);
                    window.location.href = '/admin/dashboard';
                } else {
                    document.getElementById('error').textContent = data.detail || '登录失败';
                    document.getElementById('error').style.display = 'block';
                }
            } catch (err) {
                document.getElementById('error').textContent = '网络错误';
                document.getElementById('error').style.display = 'block';
            }
        });
    </script>
</body>
</html>
    """
    return html_content


@router.post("/admin/login", tags=["管理员"])
async def admin_login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """
    管理员登录接口

    [email] 管理员邮箱
    [password] 密码
    返回 access_token
    """
    service = AdminService(db)
    try:
        user = service.verify_admin(email, password)
        access_token = create_access_token(str(user.id))
        return {"access_token": access_token, "token_type": "bearer"}
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.get("/admin/dashboard", response_class=HTMLResponse, tags=["管理员"])
async def admin_dashboard():
    """
    返回管理员控制台页面
    """
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TextLens 管理后台</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f6fa; min-height: 100vh; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 20px; }
        .header button { background: rgba(255,255,255,0.2); color: white; border: 1px solid rgba(255,255,255,0.3); padding: 8px 16px; border-radius: 6px; cursor: pointer; }
        .header button:hover { background: rgba(255,255,255,0.3); }
        .container { max-width: 1400px; margin: 0 auto; padding: 30px; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 24px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
        .stat-card h3 { color: #888; font-size: 14px; margin-bottom: 8px; }
        .stat-card .value { font-size: 32px; font-weight: 700; color: #333; }
        .card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .card-header { padding: 20px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }
        .card-header h2 { font-size: 18px; color: #333; }
        .card-body { padding: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; color: #666; font-weight: 600; font-size: 13px; }
        tr:hover { background: #f8f9fa; }
        .badge { padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 500; }
        .badge-active { background: #d4edda; color: #155724; }
        .badge-banned { background: #f8d7da; color: #721c24; }
        .badge-admin { background: #d1ecf1; color: #0c5460; }
        .btn { padding: 6px 12px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; margin-right: 5px; }
        .btn-primary { background: #667eea; color: white; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-small { padding: 4px 8px; font-size: 12px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
        .modal.active { display: flex; align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 30px; border-radius: 12px; width: 90%; max-width: 500px; }
        .modal-header { margin-bottom: 20px; }
        .modal-header h3 { font-size: 18px; color: #333; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; color: #555; font-size: 14px; }
        .form-group input, .form-group select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
        .modal-footer { margin-top: 20px; display: flex; gap: 10px; justify-content: flex-end; }
        .error { color: #e74c3c; padding: 10px; background: #f8d7da; border-radius: 6px; margin-bottom: 15px; display: none; }
        .success { color: #155724; padding: 10px; background: #d4edda; border-radius: 6px; margin-bottom: 15px; display: none; }
        .loading { text-align: center; padding: 40px; color: #888; }
    </style>
</head>
<body>
    <div class="header">
        <h1>TextLens 管理后台</h1>
        <button onclick="logout()">退出登录</button>
    </div>
    <div class="container">
        <div class="stats" id="stats">
            <div class="stat-card"><h3>总用户数</h3><div class="value" id="totalUsers">-</div></div>
            <div class="stat-card"><h3>活跃用户</h3><div class="value" id="activeUsers">-</div></div>
            <div class="stat-card"><h3>管理员</h3><div class="value" id="adminCount">-</div></div>
            <div class="stat-card"><h3>总积分</h3><div class="value" id="totalCredits">-</div></div>
        </div>
        <div class="card">
            <div class="card-header">
                <h2>用户列表</h2>
                <button class="btn btn-primary" onclick="refreshUsers()">刷新</button>
            </div>
            <div class="card-body">
                <div id="error" class="error"></div>
                <div id="success" class="success"></div>
                <table>
                    <thead>
                        <tr>
                            <th>邮箱</th>
                            <th>用户名</th>
                            <th>身份</th>
                            <th>状态</th>
                            <th>积分</th>
                            <th>注册时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="userTable"></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- 编辑用户 Modal -->
    <div class="modal" id="editModal">
        <div class="modal-content">
            <div class="modal-header"><h3>编辑用户</h3></div>
            <input type="hidden" id="editUserId">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="editUsername">
            </div>
            <div class="form-group">
                <label>管理员权限</label>
                <select id="editIsAdmin"><option value="true">是</option><option value="false">否</option></select>
            </div>
            <div class="form-group">
                <label>账户状态</label>
                <select id="editIsActive"><option value="true">启用</option><option value="false">禁用</option></select>
            </div>
            <div class="modal-footer">
                <button class="btn btn-warning" onclick="closeModal()">取消</button>
                <button class="btn btn-primary" onclick="saveUser()">保存</button>
            </div>
        </div>
    </div>

    <!-- 积分 Modal -->
    <div class="modal" id="creditModal">
        <div class="modal-content">
            <div class="modal-header"><h3>调整积分</h3></div>
            <input type="hidden" id="creditUserId">
            <div class="form-group">
                <label>当前积分</label>
                <input type="text" id="currentCredits" disabled>
            </div>
            <div class="form-group">
                <label>新积分余额</label>
                <input type="number" id="newCredits" min="0" placeholder="输入新的积分余额">
            </div>
            <div class="form-group">
                <label>原因</label>
                <input type="text" id="creditReason" placeholder="调整原因（可选）">
            </div>
            <div class="modal-footer">
                <button class="btn btn-warning" onclick="closeCreditModal()">取消</button>
                <button class="btn btn-primary" onclick="saveCredits()">确认</button>
            </div>
        </div>
    </div>

    <script>
        const token = localStorage.getItem('admin_token');
        if (!token) { window.location.href = '/admin/login'; }

        async function api(url, options = {}) {
            const resp = await fetch(url, {
                ...options,
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            if (resp.status === 401 || resp.status === 403) { logout(); return null; }
            return resp.json();
        }

        function logout() {
            localStorage.removeItem('admin_token');
            window.location.href = '/admin/login';
        }

        function showError(msg) {
            const el = document.getElementById('error');
            el.textContent = msg;
            el.style.display = 'block';
            setTimeout(() => el.style.display = 'none', 3000);
        }

        function showSuccess(msg) {
            const el = document.getElementById('success');
            el.textContent = msg;
            el.style.display = 'block';
            setTimeout(() => el.style.display = 'none', 2000);
        }

        async function refreshUsers() {
            const users = await api('/api/v1/admin/users');
            if (!users) return;
            renderUsers(users);
        }

        function renderUsers(users) {
            document.getElementById('totalUsers').textContent = users.length;
            document.getElementById('activeUsers').textContent = users.filter(u => u.is_active).length;
            document.getElementById('adminCount').textContent = users.filter(u => u.is_admin).length;
            const total = users.reduce((sum, u) => sum + (u.credits_balance || 0), 0);
            document.getElementById('totalCredits').textContent = total.toLocaleString();

            const tbody = document.getElementById('userTable');
            tbody.innerHTML = users.map(u => `
                <tr>
                    <td>${u.email}</td>
                    <td>${u.username || '-'}</td>
                    <td>${u.is_admin ? '<span class="badge badge-admin">管理员</span>' : '用户'}</td>
                    <td>${u.is_active ? '<span class="badge badge-active">正常</span>' : '<span class="badge badge-banned">已封禁</span>'}</td>
                    <td>${u.credits_balance || 0}</td>
                    <td>${new Date(u.created_at).toLocaleString('zh-CN')}</td>
                    <td>
                        <button class="btn btn-primary btn-small" onclick="editUser('${u.id}')">编辑</button>
                        <button class="btn btn-warning btn-small" onclick="adjustCredits('${u.id}')">积分</button>
                        ${u.is_active ? `<button class="btn btn-danger btn-small" onclick="banUser('${u.id}')">封禁</button>` : `<button class="btn btn-success btn-small" onclick="unbanUser('${u.id}')">解封</button>`}
                        <button class="btn btn-danger btn-small" onclick="deleteUser('${u.id}')">删除</button>
                    </td>
                </tr>
            `).join('');
        }

        async function editUser(id) {
            const users = await api('/api/v1/admin/users');
            const user = users.find(u => u.id === id);
            if (!user) return;
            document.getElementById('editUserId').value = id;
            document.getElementById('editUsername').value = user.username || '';
            document.getElementById('editIsAdmin').value = user.is_admin.toString();
            document.getElementById('editIsActive').value = user.is_active.toString();
            document.getElementById('editModal').classList.add('active');
        }

        function closeModal() { document.getElementById('editModal').classList.remove('active'); }

        async function saveUser() {
            const id = document.getElementById('editUserId').value;
            const data = {
                username: document.getElementById('editUsername').value || null,
                is_admin: document.getElementById('editIsAdmin').value === 'true',
                is_active: document.getElementById('editIsActive').value === 'true',
            };
            const result = await api('/api/v1/admin/users/' + id, { method: 'PUT', body: JSON.stringify(data) });
            if (result) { closeModal(); showSuccess('保存成功'); refreshUsers(); }
        }

        async function adjustCredits(id) {
            const users = await api('/api/v1/admin/users');
            const user = users.find(u => u.id === id);
            if (!user) return;
            document.getElementById('creditUserId').value = id;
            document.getElementById('currentCredits').value = user.credits_balance || 0;
            document.getElementById('newCredits').value = '';
            document.getElementById('creditReason').value = '';
            document.getElementById('creditModal').classList.add('active');
        }

        function closeCreditModal() { document.getElementById('creditModal').classList.remove('active'); }

        async function saveCredits() {
            const id = document.getElementById('creditUserId').value;
            const credits = parseInt(document.getElementById('newCredits').value);
            const reason = document.getElementById('creditReason').value;
            if (isNaN(credits) || credits < 0) { showError('请输入有效的积分数量'); return; }
            const result = await api('/api/v1/admin/users/' + id + '/credits', {
                method: 'POST',
                body: JSON.stringify({ credits, reason })
            });
            if (result) { closeCreditModal(); showSuccess('积分已更新'); refreshUsers(); }
        }

        async function banUser(id) {
            if (!confirm('确定要封禁该用户吗？')) return;
            const result = await api('/api/v1/admin/users/' + id + '/ban', { method: 'POST' });
            if (result) { showSuccess('用户已封禁'); refreshUsers(); }
        }

        async function unbanUser(id) {
            if (!confirm('确定要解封该用户吗？')) return;
            const result = await api('/api/v1/admin/users/' + id + '/unban', { method: 'POST' });
            if (result) { showSuccess('用户已解封'); refreshUsers(); }
        }

        async function deleteUser(id) {
            if (!confirm('确定要删除该用户吗？此操作不可恢复！')) return;
            if (!confirm('再次确认：删除用户将清除所有数据？')) return;
            const result = await api('/api/v1/admin/users/' + id, { method: 'DELETE' });
            if (result) { showSuccess('用户已删除'); refreshUsers(); }
        }

        refreshUsers();
    </script>
</body>
</html>
    """
    return html_content


@router.get("/admin/users", tags=["管理员"])
async def list_users(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    获取所有用户列表（需要管理员权限）

    返回用户列表，包含积分信息
    """
    service = AdminService(db)
    users = service.get_all_users()
    result = []
    for user in users:
        credits = service.get_user_credits(user.id)
        result.append({
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "is_email_verified": user.is_email_verified,
            "credits_balance": credits.balance if credits else 0,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        })
    return result


@router.put("/admin/users/{user_id}", tags=["管理员"])
async def update_user(
    user_id: UUID,
    request: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    更新用户信息（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    user = service.update_user(
        user_id,
        username=request.username,
        is_admin=request.is_admin,
        is_active=request.is_active,
    )
    return {"message": "User updated successfully"}


@router.get("/admin/users/{user_id}", tags=["管理员"])
async def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    获取单个用户详情（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    user = service.get_user_by_id(user_id)
    credits = service.get_user_credits(user_id)
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "credits_balance": credits.balance if credits else 0,
        "total_earned": credits.total_earned if credits else 0,
        "total_spent": credits.total_spent if credits else 0,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.post("/admin/users/{user_id}/credits", tags=["管理员"])
async def adjust_user_credits(
    user_id: UUID,
    request: AdjustCreditsRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    调整用户积分（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    service.set_user_credits(user_id, request.credits, request.reason or "")
    return {"message": "Credits adjusted successfully"}


@router.post("/admin/users/{user_id}/ban", tags=["管理员"])
async def ban_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    封禁用户（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    service.ban_user(user_id)
    return {"message": "User banned successfully"}


@router.post("/admin/users/{user_id}/unban", tags=["管理员"])
async def unban_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    解封用户（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    service.unban_user(user_id)
    return {"message": "User unbanned successfully"}


@router.delete("/admin/users/{user_id}", tags=["管理员"])
async def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_admin_user),
):
    """
    删除用户（需要管理员权限）

    [user_id] 用户UUID
    """
    service = AdminService(db)
    service.delete_user(user_id)
    return {"message": "User deleted successfully"}

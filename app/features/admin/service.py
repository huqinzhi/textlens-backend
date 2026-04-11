"""
管理员业务逻辑服务层
处理用户管理、积分管理等管理员操作
"""
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.db.models.user import User
from app.db.models.credit import CreditAccount, CreditTransaction
from app.core.constants import CreditTransactionType, CreditSourceType
from app.core.security import verify_password, hash_password
from app.core.exceptions import NotFoundError, ValidationError, AuthenticationError


class AdminService:
    """
    管理员服务类

    处理用户管理和积分管理等管理员操作。
    [db] SQLAlchemy 数据库会话
    """

    def __init__(self, db: Session):
        self.db = db

    def verify_admin(self, email: str, password: str) -> User:
        """
        验证管理员登录

        [email] 管理员邮箱
        [password] 密码
        返回 User 管理员用户对象
        """
        user = self.db.query(User).filter(
            User.email == email,
            User.is_admin == True,
            User.deleted_at.is_(None),
        ).first()

        if not user:
            raise AuthenticationError("Invalid admin credentials")

        if not verify_password(password, user.password_hash or ""):
            raise AuthenticationError("Invalid admin credentials")

        return user

    def get_all_users(self) -> List[User]:
        """
        获取所有用户列表

        返回 List[User] 用户列表
        """
        return self.db.query(User).filter(
            User.deleted_at.is_(None)
        ).order_by(User.created_at.desc()).all()

    def get_user_by_id(self, user_id: UUID) -> User:
        """
        根据ID获取用户详情

        [user_id] 用户UUID
        返回 User 用户对象
        """
        user = self.db.query(User).filter(
            User.id == user_id,
            User.deleted_at.is_(None),
        ).first()

        if not user:
            raise NotFoundError("User not found")
        return user

    def get_user_credits(self, user_id: UUID) -> Optional[CreditAccount]:
        """
        获取用户积分账户

        [user_id] 用户UUID
        返回 CreditAccount 积分账户对象
        """
        return self.db.query(CreditAccount).filter(
            CreditAccount.user_id == user_id
        ).first()

    def update_user(self, user_id: UUID, **kwargs) -> User:
        """
        更新用户信息

        [user_id] 用户UUID
        [kwargs] 要更新的字段
        返回 User 更新后的用户对象
        """
        user = self.get_user_by_id(user_id)

        # 允许更新的字段
        allowed_fields = ["username", "is_admin", "is_active", "age_verified"]
        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(user, key, value)

        self.db.commit()
        self.db.refresh(user)
        return user

    def ban_user(self, user_id: UUID) -> User:
        """
        封禁用户

        [user_id] 用户UUID
        返回 User 更新后的用户对象
        """
        user = self.get_user_by_id(user_id)
        user.is_active = False
        self.db.commit()
        self.db.refresh(user)
        return user

    def unban_user(self, user_id: UUID) -> User:
        """
        解封用户

        [user_id] 用户UUID
        返回 User 更新后的用户对象
        """
        user = self.get_user_by_id(user_id)
        user.is_active = True
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: UUID) -> None:
        """
        删除用户（软删除）

        [user_id] 用户UUID
        """
        from datetime import datetime
        user = self.get_user_by_id(user_id)
        user.deleted_at = datetime.utcnow()
        user.is_active = False
        self.db.commit()

    def adjust_credits(self, user_id: UUID, amount: int, reason: str = "") -> CreditAccount:
        """
        调整用户积分

        [user_id] 用户UUID
        [amount] 积分变动数量（正为增加，负为扣除）
        [reason] 变动原因
        返回 CreditAccount 更新后的积分账户
        """
        credit_account = self.get_user_credits(user_id)
        if not credit_account:
            # 如果没有积分账户，创建一个
            credit_account = CreditAccount(
                user_id=user_id,
                balance=0,
                total_earned=0,
                total_spent=0,
            )
            self.db.add(credit_account)
            self.db.flush()

        # 更新积分
        credit_account.balance += amount

        if amount > 0:
            credit_account.total_earned += amount
            tx_type = CreditTransactionType.earn
        else:
            credit_account.total_spent += abs(amount)
            tx_type = CreditTransactionType.spend

        # 记录流水
        transaction = CreditTransaction(
            user_id=user_id,
            credit_account_id=credit_account.id,
            amount=amount,
            type=tx_type,
            source=CreditSourceType.admin_adjust,
            ref_id=str(user_id),
            description=f"管理员调整: {reason}" if reason else "管理员调整积分",
            balance_after=credit_account.balance,
        )
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(credit_account)
        return credit_account

    def set_user_credits(self, user_id: UUID, new_balance: int, reason: str = "") -> CreditAccount:
        """
        设置用户积分为指定值

        [user_id] 用户UUID
        [new_balance] 新的积分余额
        [reason] 变动原因
        返回 CreditAccount 更新后的积分账户
        """
        credit_account = self.get_user_credits(user_id)
        if not credit_account:
            credit_account = CreditAccount(
                user_id=user_id,
                balance=new_balance,
                total_earned=new_balance,
                total_spent=0,
            )
            self.db.add(credit_account)
            self.db.flush()
            return credit_account

        diff = new_balance - credit_account.balance
        return self.adjust_credits(user_id, diff, reason)

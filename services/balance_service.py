import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Точность до копеек для денежных операций
KOPECK = Decimal('0.01')


def get_db():
    """Lazy import to avoid circular dependency"""
    from app import db
    return db


class BalanceService:
    """
    Service for managing user balance operations
    Handles credits, debits, and balance inquiries
    """
    
    @staticmethod
    def get_or_create_user_balance(user_id):
        """
        Get or create UserBalance for a user
        
        Args:
            user_id: User ID
            
        Returns:
            UserBalance: User's balance record
            
        Raises:
            ValueError: If user_id is invalid
        """
        from models import UserBalance, User
        db = get_db()
        
        if not user_id:
            raise ValueError("user_id is required")
        
        try:
            user = User.query.get(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            balance = UserBalance.query.filter_by(user_id=user_id).first()
            
            if not balance:
                logger.info(f"Creating new balance for user {user_id}")
                balance = UserBalance()
                balance.user_id = user_id
                balance.balance = Decimal('0.00')
                balance.pending_balance = Decimal('0.00')
                balance.total_earned = Decimal('0.00')
                balance.total_withdrawn = Decimal('0.00')
                balance.currency = 'RUB'
                db.session.add(balance)
                db.session.flush()  # Flush instead of commit - let outer transaction handle commit
                logger.info(f"✅ Created balance for user {user_id}")
            
            return balance
            
        except SQLAlchemyError as e:
            logger.error(f"❌ Database error creating balance for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error creating balance for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_balance(user_id):
        """
        Get current balance for a user
        
        Args:
            user_id: User ID
            
        Returns:
            dict: Balance information with keys:
                - available_amount: Available for withdrawal (string with kopeck precision)
                - pending_amount: Pending withdrawal (string with kopeck precision)
                - total_earned: Total earned (string with kopeck precision)
                - total_withdrawn: Total withdrawn (string with kopeck precision)
                - currency: Currency code
        """
        from models import UserBalance
        
        try:
            balance = BalanceService.get_or_create_user_balance(user_id)
            
            # Quantize to kopeck precision, then convert to string
            available = balance.balance.quantize(KOPECK, rounding=ROUND_HALF_UP)
            pending = balance.pending_balance.quantize(KOPECK, rounding=ROUND_HALF_UP)
            earned = balance.total_earned.quantize(KOPECK, rounding=ROUND_HALF_UP)
            withdrawn = balance.total_withdrawn.quantize(KOPECK, rounding=ROUND_HALF_UP)
            
            return {
                'available_amount': str(available),
                'pending_amount': str(pending),
                'total_earned': str(earned),
                'total_withdrawn': str(withdrawn),
                'currency': balance.currency,
                'last_transaction_at': balance.last_updated
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting balance for user {user_id}: {e}")
            raise
    
    @staticmethod
    def credit_balance(user_id, amount, description, transaction_type='cashback_earned', 
                      deal_id=None, cashback_application_id=None, created_by_id=None):
        """
        Credit (add) funds to user balance
        
        Args:
            user_id: User ID
            amount: Amount to credit (must be > 0)
            description: Transaction description
            transaction_type: Type of transaction (registration_bonus, cashback_earned, refund, bonus, adjustment)
            deal_id: Related deal ID (optional)
            cashback_application_id: Related cashback application ID (optional)
            created_by_id: Admin ID who created transaction (optional)
            
        Returns:
            BalanceTransaction: Created transaction record
            
        Raises:
            ValueError: If validation fails
        """
        from models import UserBalance, BalanceTransaction
        db = get_db()
        
        if not user_id:
            raise ValueError("user_id is required")
        
        if not amount or amount <= 0:
            raise ValueError("amount must be greater than 0")
        
        if not description:
            raise ValueError("description is required")
        
        amount = Decimal(str(amount))
        
        try:
            with db.session.begin_nested():
                balance = BalanceService.get_or_create_user_balance(user_id)
                
                balance_before = balance.balance
                balance_after = balance_before + amount
                
                balance.balance = balance_after
                balance.total_earned += amount
                balance.last_updated = datetime.utcnow()
                balance.updated_at = datetime.utcnow()
                
                transaction = BalanceTransaction()
                transaction.user_id = user_id
                transaction.amount = amount
                transaction.transaction_type = transaction_type
                transaction.description = description
                transaction.balance_before = balance_before
                transaction.balance_after = balance_after
                transaction.deal_id = deal_id
                transaction.cashback_application_id = cashback_application_id
                transaction.created_by_id = created_by_id
                transaction.status = 'completed'
                transaction.processed_at = datetime.utcnow()
                
                db.session.add(transaction)
            
            db.session.commit()
            
            logger.info(f"✅ Credited {amount}₽ to user {user_id} balance "
                       f"(type: {transaction_type}, new balance: {balance_after}₽)")
            
            return transaction
            
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"❌ Database error crediting balance for user {user_id}: {e}")
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error crediting balance for user {user_id}: {e}")
            raise
    
    @staticmethod
    def debit_balance(user_id, amount, description, transaction_type='withdrawal',
                     withdrawal_request_id=None, created_by_id=None):
        """
        Debit (subtract) funds from user balance
        
        Args:
            user_id: User ID
            amount: Amount to debit (must be > 0)
            description: Transaction description
            transaction_type: Type of transaction (withdrawal, adjustment)
            withdrawal_request_id: Related withdrawal request ID (optional)
            created_by_id: Admin ID who created transaction (optional)
            
        Returns:
            BalanceTransaction: Created transaction record
            
        Raises:
            ValueError: If validation fails or insufficient balance
        """
        from models import UserBalance, BalanceTransaction
        db = get_db()
        
        if not user_id:
            raise ValueError("user_id is required")
        
        if not amount or amount <= 0:
            raise ValueError("amount must be greater than 0")
        
        if not description:
            raise ValueError("description is required")
        
        amount = Decimal(str(amount))
        
        try:
            with db.session.begin_nested():
                balance = BalanceService.get_or_create_user_balance(user_id)
                
                if balance.balance < amount:
                    raise ValueError(
                        f"Insufficient balance: available {balance.balance}₽, "
                        f"requested {amount}₽"
                    )
                
                balance_before = balance.balance
                balance_after = balance_before - amount
                
                balance.balance = balance_after
                balance.total_withdrawn += amount
                balance.last_updated = datetime.utcnow()
                balance.updated_at = datetime.utcnow()
                
                transaction = BalanceTransaction()
                transaction.user_id = user_id
                transaction.amount = -amount
                transaction.transaction_type = transaction_type
                transaction.description = description
                transaction.balance_before = balance_before
                transaction.balance_after = balance_after
                transaction.withdrawal_request_id = withdrawal_request_id
                transaction.created_by_id = created_by_id
                transaction.status = 'completed'
                transaction.processed_at = datetime.utcnow()
                
                db.session.add(transaction)
            
            db.session.commit()
            
            logger.info(f"✅ Debited {amount}₽ from user {user_id} balance "
                       f"(type: {transaction_type}, new balance: {balance_after}₽)")
            
            return transaction
            
        except ValueError as e:
            db.session.rollback()
            logger.warning(f"⚠️  Validation error debiting balance for user {user_id}: {e}")
            raise
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"❌ Database error debiting balance for user {user_id}: {e}")
            raise
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Error debiting balance for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_transaction_history(user_id, limit=50, offset=0):
        """
        Get transaction history for a user
        
        Args:
            user_id: User ID
            limit: Maximum number of transactions to return
            offset: Number of transactions to skip
            
        Returns:
            list: List of BalanceTransaction objects ordered by created_at desc
        """
        from models import BalanceTransaction
        
        try:
            transactions = BalanceTransaction.query.filter_by(
                user_id=user_id
            ).order_by(
                desc(BalanceTransaction.created_at)
            ).limit(limit).offset(offset).all()
            
            logger.info(f"Retrieved {len(transactions)} transactions for user {user_id}")
            
            return transactions
            
        except Exception as e:
            logger.error(f"❌ Error getting transaction history for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_transaction_count(user_id):
        """
        Get total transaction count for a user
        
        Args:
            user_id: User ID
            
        Returns:
            int: Total number of transactions
        """
        from models import BalanceTransaction
        
        try:
            count = BalanceTransaction.query.filter_by(user_id=user_id).count()
            return count
            
        except Exception as e:
            logger.error(f"❌ Error getting transaction count for user {user_id}: {e}")
            raise

from datetime import datetime
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import json

# Import db from app after it's initialized
try:
    from app import db
except ImportError:
    # Fallback for when app is not yet available
    class Base(DeclarativeBase):
        pass
    db = SQLAlchemy(model_class=Base)


class Region(db.Model):
    """Region model for multi-regional support"""
    __tablename__ = 'regions'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    
    # Contact information
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    
    # Map configuration  
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    zoom_level = db.Column(db.Integer, default=8)
    
    # DaData FIAS ID for geocoding
    fias_id = db.Column(db.String(36), nullable=True)
    
    # SEO and content
    description = db.Column(db.Text, nullable=True)
    meta_title = db.Column(db.String(200), nullable=True)
    meta_description = db.Column(db.String(300), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    cities = db.relationship('City', backref='region', lazy=True)
    
    def __repr__(self):
        return f'<Region {self.name}>'


class City(db.Model):
    """City model for multi-city support within regions"""
    __tablename__ = 'cities'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    region_id = db.Column(db.Integer, db.ForeignKey('regions.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)
    
    # Russian grammar cases for SEO and content
    name_genitive = db.Column(db.String(100), nullable=True)  # родительный: Краснодара, Сочи
    name_prepositional = db.Column(db.String(100), nullable=True)  # предложный: Краснодаре, Сочи
    
    # Contact information
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    
    # Map configuration
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    zoom_level = db.Column(db.Integer, default=12)
    
    # DaData FIAS ID for geocoding
    fias_id = db.Column(db.String(36), nullable=True)
    
    # SEO and content
    description = db.Column(db.Text, nullable=True)
    meta_title = db.Column(db.String(200), nullable=True)
    meta_description = db.Column(db.String(300), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Ensure unique city names within regions, but allow same name in different regions
    __table_args__ = (
        db.UniqueConstraint('region_id', 'name', name='unique_city_per_region'),
        db.UniqueConstraint('region_id', 'slug', name='unique_slug_per_region'),
        {'extend_existing': True}
    )
    
    def __repr__(self):
        return f'<City {self.name} in {self.region.name if self.region else "Unknown Region"}>'


class Developer(db.Model):
    """Developer/Builder model with full company information including AI-parsed data"""
    __tablename__ = 'developers'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    slug = db.Column(db.String(200), nullable=False, unique=True)
    
    # External ID for parser integration
    external_id = db.Column(db.String(200), nullable=True, unique=True, index=True)  # ID from external source (parser/API)
    
    # Company Information
    full_name = db.Column(db.String(300), nullable=True)  # ООО "Компания"
    established_year = db.Column(db.Integer, nullable=True)  # Год основания
    description = db.Column(db.Text, nullable=True)  # Описание компании
    logo_url = db.Column(db.String(300), nullable=True)
    
    # Contact Information
    phone = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    address = db.Column(db.String(300), nullable=True)
    
    # Location and Map
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    zoom_level = db.Column(db.Integer, default=13)
    
    # Statistics (AI-parsed from Domclick)
    total_complexes = db.Column(db.Integer, default=0)
    total_properties = db.Column(db.Integer, default=0)
    properties_sold = db.Column(db.Integer, default=0)
    rating = db.Column(db.Float, default=4.8)
    experience_years = db.Column(db.Integer, default=10)
    
    # Domclick-specific statistics
    completed_buildings = db.Column(db.Integer, default=0)  # Сдано домов
    under_construction = db.Column(db.Integer, default=0)  # Строится домов
    completed_complexes = db.Column(db.Integer, default=0)  # Сдано ЖК
    construction_complexes = db.Column(db.Integer, default=0)  # Строится ЖК
    on_time_percentage = db.Column(db.Integer, default=0)  # Процент сдачи в срок
    
    # Additional AI-parsed data
    founded_year = db.Column(db.Integer, nullable=True)  # Год основания из парсера
    total_area_built = db.Column(db.String(100), nullable=True)  # Общая площадь построенного
    completed_projects = db.Column(db.Integer, default=0)  # Завершенных проектов
    employees_count = db.Column(db.Integer, default=0)  # Количество сотрудников
    market_position = db.Column(db.String(200), nullable=True)  # Позиция на рынке
    specialization = db.Column(db.String(300), nullable=True)  # Специализация
    
    # Sberbank verification (AI-parsed)
    sber_verified = db.Column(db.Boolean, default=False)  # Проверено Сбербанком
    no_bankruptcy = db.Column(db.Boolean, default=False)  # Нет признаков банкротства
    quarterly_checks = db.Column(db.Boolean, default=False)  # Ежеквартальная проверка
    actual_documents = db.Column(db.Boolean, default=False)  # Актуальные документы
    
    # Financial Information
    min_price = db.Column(db.Integer, nullable=True)
    max_cashback_percent = db.Column(db.Float, default=10.0)
    
    # Company Details
    inn = db.Column(db.String(20), nullable=True)  # ИНН
    kpp = db.Column(db.String(20), nullable=True)  # КПП
    ogrn = db.Column(db.String(20), nullable=True)  # ОГРН
    legal_address = db.Column(db.String(300), nullable=True)
    bank_name = db.Column(db.String(200), nullable=True)
    bank_bik = db.Column(db.String(20), nullable=True)
    bank_account = db.Column(db.String(30), nullable=True)
    
    # Features and residential complexes (JSON format)
    features = db.Column(db.Text, nullable=True)  # JSON array of features
    infrastructure = db.Column(db.Text, nullable=True)  # JSON array of infrastructure
    advantages = db.Column(db.Text, nullable=True)  # JSON array of advantages (преимущества)
    residential_complexes = db.Column(db.Text, nullable=True)  # JSON array of complexes from AI parser
    
    # Parsing metadata
    source_url = db.Column(db.String(500), nullable=True)  # URL источника для парсера
    parsed_at = db.Column(db.DateTime, nullable=True)  # Когда последний раз парсилось
    parsing_status = db.Column(db.String(50), default='not_parsed')  # not_parsed, parsing, success, error
    parsing_error = db.Column(db.Text, nullable=True)  # Ошибки парсинга
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_partner = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_residential_complexes_list(self):
        """Get residential complexes as list"""
        import json
        try:
            if self.residential_complexes:
                return json.loads(self.residential_complexes)
            return []
        except:
            return []
    
    def set_residential_complexes_list(self, complexes_list):
        """Set residential complexes from list"""
        import json
        try:
            self.residential_complexes = json.dumps(complexes_list, ensure_ascii=False)
        except:
            self.residential_complexes = "[]"
    
    def get_verification_status(self):
        """Get verification status summary"""
        verifications = [
            self.sber_verified,
            self.no_bankruptcy, 
            self.quarterly_checks,
            self.actual_documents
        ]
        return sum(verifications)
    
    def __repr__(self):
        return f'<Developer {self.name}>'


class DeveloperAppointment(db.Model):
    """Developer appointment model"""
    __tablename__ = 'developer_appointments'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Allow null for anonymous applications
    property_id = db.Column(db.String(50), nullable=True)  # Property ID from JSON - allow null for general applications
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'), nullable=True)
    developer_name = db.Column(db.String(200), nullable=False)
    complex_name = db.Column(db.String(200), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    appointment_time = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(50), default='Запланирована')  # Запланирована, Завершена, Отменена
    client_name = db.Column(db.String(200), nullable=False)
    client_phone = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='developer_appointments')
    developer = db.relationship('Developer', backref='appointments')


class CallbackRequest(db.Model):
    """Callback request model"""
    __tablename__ = 'callback_requests'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    preferred_time = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Quiz responses
    interest = db.Column(db.String(100), nullable=True)  # What they're interested in
    budget = db.Column(db.String(50), nullable=True)    # Budget range
    timing = db.Column(db.String(50), nullable=True)    # When they plan to buy
    
    # Status tracking
    status = db.Column(db.String(50), default='Новая')  # Новая, Обработана, Звонок совершен
    assigned_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    manager_notes = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    assigned_manager = db.relationship('Manager', backref='callback_requests')
    
    def __repr__(self):
        return f'<CallbackRequest {self.name} - {self.phone}>'

class User(UserMixin, db.Model):
    """User model for authentication"""
    __tablename__ = 'users'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)  # Nullable для двухэтапной регистрации
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)  # Телефон обязателен и уникален
    telegram_id = db.Column(db.String(50), nullable=True)  # Telegram chat ID
    full_name = db.Column(db.String(100), nullable=True)  # Nullable для двухэтапной регистрации
    password_hash = db.Column(db.String(256), nullable=True)  # Allow null for users created by managers
    temp_password_hash = db.Column(db.String(256), nullable=True)  # Temporary password for new users
    created_by_admin = db.Column(db.Boolean, default=False)  # Track if user created by admin
    phone_verified = db.Column(db.Boolean, default=False)  # Флаг верификации телефона
    profile_completed = db.Column(db.Boolean, default=False)  # Флаг завершения профиля (Шаг 2)
    must_change_password = db.Column(db.Boolean, default=False)  # Требуется смена временного пароля
    
    # Notification preferences
    preferred_contact = db.Column(db.String(20), default='email')  # phone, email, telegram, whatsapp, both
    email_notifications = db.Column(db.Boolean, default=True)
    telegram_notifications = db.Column(db.Boolean, default=False)
    notify_recommendations = db.Column(db.Boolean, default=True)
    notify_saved_searches = db.Column(db.Boolean, default=True)
    notify_applications = db.Column(db.Boolean, default=True)
    notify_cashback = db.Column(db.Boolean, default=True)
    notify_marketing = db.Column(db.Boolean, default=False)
    
    # Profile info
    profile_image = db.Column(db.String(200), nullable=True, default=None)
    date_of_birth = db.Column(db.Date, nullable=True)  # Дата рождения
    last_ip = db.Column(db.String(45), nullable=True)  # Last login IP
    last_user_agent = db.Column(db.String(500), nullable=True)  # Last login User Agent
    user_id = db.Column(db.String(20), unique=True, nullable=False)  # CB12345678 format
    role = db.Column(db.String(20), default='buyer')  # buyer, manager, admin
    
    # Status and verification
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), nullable=True)
    is_demo = db.Column(db.Boolean, default=False)  # Demo account flag
    
    # Client management
    registration_source = db.Column(db.String(50), default='Website')
    client_notes = db.Column(db.Text, nullable=True)
    assigned_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    client_status = db.Column(db.String(50), default='Новый')
    
    # Registration quiz preferences
    preferred_district = db.Column(db.String(100))  # Step 1: District selection
    property_type = db.Column(db.String(50))  # Step 2: Property type (квартира, таунхаус, дом)
    room_count = db.Column(db.String(20))  # Step 3: Room count  
    budget_range = db.Column(db.String(50))  # Step 4: Budget range
    quiz_completed = db.Column(db.Boolean, default=False)
    
    
    # Balance and bonus system
    balance = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Текущий баланс в рублях
    registration_bonus = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Начисляется при регистрации
    total_earned = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Всего заработано кешбека
    total_withdrawn = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Всего выведено
    
    # Relationship to manager
    assigned_manager = db.relationship('Manager', backref='assigned_clients')
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    cashback_records = db.relationship('CashbackRecord', backref='user', lazy=True)
    applications = db.relationship('Application', backref='user', lazy=True)
    favorites = db.relationship('Favorite', backref='user', lazy=True)
    saved_searches = db.relationship('SavedSearch', back_populates='user', lazy=True)
    
    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        if not self.user_id:
            self.user_id = self.generate_user_id()
    
    def generate_user_id(self):
        """Generate unique user ID in format CB12345678"""
        import random
        while True:
            user_id = f"CB{random.randint(10000000, 99999999)}"
            if not User.query.filter_by(user_id=user_id).first():
                return user_id
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        if not self.password_hash:
            return False  # No password set yet
        return check_password_hash(self.password_hash, password)
    
    def needs_password_setup(self):
        """Check if user needs to set up password"""
        return not self.password_hash
    
    def generate_verification_token(self):
        """Generate verification token"""
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    
    def get_total_cashback(self):
        """Get total cashback amount"""
        total = sum(record.amount for record in self.cashback_records if record.status == 'paid')
        return total or 0
    
    def get_pending_cashback(self):
        """Get pending cashback amount"""
        total = sum(record.amount for record in self.cashback_records if record.status == 'pending')
        return total or 0
    
    def __repr__(self):
        phone_display = self.phone if self.phone else "no phone"
        email_display = self.email if self.email else "no email"
        return f'<User {phone_display} / {email_display}>'


class PhoneVerification(db.Model):
    """SMS verification codes for phone registration/login"""
    __tablename__ = 'phone_verifications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(50), default='registration', nullable=False)  # registration, login, password_reset
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    
    # Статус верификации
    is_verified = db.Column(db.Boolean, default=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    
    # TTL и попытки
    attempts = db.Column(db.Integer, default=0)  # Количество попыток ввода
    max_attempts = db.Column(db.Integer, default=3)  # Максимум попыток
    expires_at = db.Column(db.DateTime, nullable=False)  # Истекает через 10 минут
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def is_expired(self):
        """Проверка, истек ли код"""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self):
        """Проверка валидности кода (не истек, не превышен лимит попыток, не использован)"""
        return not self.is_expired() and self.attempts < self.max_attempts and not self.is_verified
    
    def increment_attempts(self):
        """Увеличить счетчик попыток"""
        self.attempts += 1
    
    def mark_verified(self):
        """Отметить как верифицированный"""
        self.is_verified = True
        self.verified_at = datetime.utcnow()
    
    @classmethod
    def create_code(cls, phone, purpose='registration', ip_address=None, user_agent=None):
        """Создать новый код верификации"""
        import random
        from datetime import timedelta
        
        # Use 4 digits for password reset, 6 digits for registration/login
        code_length = 4 if purpose == 'password_reset' else 6
        code = ''.join([str(random.randint(0, 9)) for _ in range(code_length)])
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        
        verification = cls(
            phone=phone,
            code=code,
            purpose=purpose,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        return verification
    
    @classmethod
    def can_send_code(cls, phone, rate_limit_seconds=60):
        """Проверить, можно ли отправить новый код (rate limiting)"""
        from datetime import timedelta
        time_threshold = datetime.utcnow() - timedelta(seconds=rate_limit_seconds)
        recent_code = cls.query.filter(
            cls.phone == phone,
            cls.created_at > time_threshold
        ).first()
        return recent_code is None
    
    def __repr__(self):
        return f'<PhoneVerification {self.phone} - {self.code}>'


class PhoneChangeRequest(db.Model):
    """Запрос на смену номера телефона с SMS верификацией"""
    __tablename__ = 'phone_change_requests'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    new_phone = db.Column(db.String(20), nullable=False)
    verification_code = db.Column(db.String(6), nullable=False)
    attempts = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=5)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, verified, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Temporarily commented out due to missing table phone_change_requests
    # user = db.relationship('User', backref='phone_change_requests')
    
    def is_expired(self):
        """Проверка, истек ли код"""
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self):
        """Проверка валидности запроса (не истек, не превышен лимит попыток, pending)"""
        return not self.is_expired() and self.attempts < self.max_attempts and self.status == 'pending'
    
    def increment_attempts(self):
        """Увеличить счетчик попыток"""
        self.attempts += 1
    
    def mark_verified(self):
        """Отметить как верифицированный"""
        self.status = 'verified'
    
    def mark_expired(self):
        """Отметить как истекший"""
        self.status = 'expired'
    
    @classmethod
    def create_request(cls, user_id, new_phone):
        """Создать новый запрос на смену номера"""
        import random
        from datetime import timedelta
        
        # Генерируем 6-значный код
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        
        request = cls(
            user_id=user_id,
            new_phone=new_phone,
            verification_code=code,
            expires_at=expires_at
        )
        return request
    
    @classmethod
    def can_request_new_code(cls, user_id, rate_limit_seconds=60):
        """Проверить, можно ли отправить новый код (rate limiting)"""
        from datetime import timedelta
        time_threshold = datetime.utcnow() - timedelta(seconds=rate_limit_seconds)
        recent_request = cls.query.filter(
            cls.user_id == user_id,
            cls.status == 'pending',
            cls.created_at > time_threshold
        ).first()
        return recent_request is None
    
    def __repr__(self):
        return f'<PhoneChangeRequest {self.user_id} -> {self.new_phone}>'


class EmailChangeRequest(db.Model):
    """Запрос на смену email с верификацией через ссылку"""
    __tablename__ = 'email_change_requests'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    new_email = db.Column(db.String(120), nullable=False)
    verification_token = db.Column(db.String(100), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, verified, expired
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Temporarily commented out due to missing table email_change_requests
    # user = db.relationship('User', backref='email_change_requests')
    
    def is_expired(self):
        """Проверка, истек ли токен"""
        return datetime.utcnow() > self.expires_at
    
    def mark_verified(self):
        """Отметить как подтвержденный"""
        self.status = 'verified'
    
    def mark_expired(self):
        """Отметить как истекший"""
        self.status = 'expired'
    
    @classmethod
    def create_request(cls, user_id, new_email):
        """Создать новый запрос на смену email"""
        import secrets
        from datetime import timedelta
        
        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        request = cls(
            user_id=user_id,
            new_email=new_email,
            verification_token=token,
            expires_at=expires_at
        )
        return request
    
    @classmethod
    def can_request_new_token(cls, user_id, rate_limit_seconds=60):
        """Проверить, можно ли отправить новый токен (rate limiting)"""
        from datetime import timedelta
        time_threshold = datetime.utcnow() - timedelta(seconds=rate_limit_seconds)
        recent_request = cls.query.filter(
            cls.user_id == user_id,
            cls.status == 'pending',
            cls.created_at > time_threshold
        ).first()
        return recent_request is None
    
    def __repr__(self):
        return f'<EmailChangeRequest {self.user_id} -> {self.new_email}>'


class Manager(UserMixin, db.Model):
    """Manager model for staff authentication and client management"""
    __tablename__ = 'managers'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    position = db.Column(db.String(50), default='Менеджер')
    years_of_experience = db.Column(db.Integer, nullable=True, default=1)
    
    # Manager permissions and limits
    can_approve_cashback = db.Column(db.Boolean, default=True)
    can_manage_documents = db.Column(db.Boolean, default=True)
    can_create_collections = db.Column(db.Boolean, default=True)
    max_cashback_approval = db.Column(db.Integer, default=500000)  # Maximum amount they can approve
    
    # Status and profile
    is_active = db.Column(db.Boolean, default=True)
    is_rop = db.Column(db.Boolean, default=False)  # РОП (руководитель отдела продаж)
    profile_image = db.Column(db.String(200), default='https://randomuser.me/api/portraits/men/45.jpg')
    last_ip = db.Column(db.String(45), nullable=True)
    last_user_agent = db.Column(db.String(500), nullable=True)
    manager_id = db.Column(db.String(20), unique=True, nullable=False)  # MNG12345678 format
    
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    org_role_id = db.Column(db.Integer, db.ForeignKey('org_roles.id'), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    def __init__(self, **kwargs):
        super(Manager, self).__init__(**kwargs)
        if not self.manager_id:
            self.manager_id = self.generate_manager_id()
    
    def generate_manager_id(self):
        """Generate unique manager ID in format MNG12345678"""
        import random
        while True:
            manager_id = f"MNG{random.randint(10000000, 99999999)}"
            if not Manager.query.filter_by(manager_id=manager_id).first():
                return manager_id
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    @property
    def display_position(self):
        if self.org_role_id and self.org_role:
            return self.org_role.name
        return self.position if self.position else 'Менеджер'

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def name(self):
        """Alias for full_name for compatibility"""
        return self.full_name
    
    def get_client_count(self):
        """Get number of assigned clients"""
        return User.query.filter_by(assigned_manager_id=self.id).count()
    
    def get_active_applications(self):
        """Get active cashback applications from assigned clients"""
        return CashbackApplication.query.join(User).filter(
            User.assigned_manager_id == self.id,
            CashbackApplication.status.in_(['На рассмотрении', 'Требуются документы'])
        ).count()
    
    def get_total_approved_cashback(self):
        """Get total cashback amount approved by this manager"""
        applications = CashbackApplication.query.join(User).filter(
            User.assigned_manager_id == self.id,
            CashbackApplication.status == 'Одобрена'
        ).all()
        return sum(app.cashback_amount for app in applications)
    
    def get_active_deals_count(self):
        """Get count of active deals for this manager"""
        return CashbackApplication.query.join(User).filter(
            User.assigned_manager_id == self.id,
            CashbackApplication.status.in_(['На рассмотрении', 'Требуются документы', 'Одобрена'])
        ).count()
    
    def get_id(self):
        """Override UserMixin get_id to return prefixed ID for Flask-Login"""
        return f'm_{self.id}'
    
    @property
    def role(self):
        """Return role for compatibility"""
        return 'manager'
    
    def to_dict(self):
        """Convert manager to dictionary"""
        return {
            'id': self.id,
            'email': self.email,
            'full_name': self.full_name,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'position': self.position,
            'manager_id': self.manager_id,
            'is_active': self.is_active,
            'profile_image': self.profile_image,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

    def __repr__(self):
        return f'<Manager {self.email}>'


class SearchHistory(db.Model):
    """Search history model for tracking user/manager searches"""
    __tablename__ = 'search_history'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(500), nullable=False)  # Search query text
    
    # User tracking - either user_id OR manager_id will be set
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    
    # Search context
    result_count = db.Column(db.Integer, default=0)  # Number of results found
    filters_used = db.Column(db.Text, nullable=True)  # JSON of filters applied
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = db.relationship('User', backref='search_history')
    manager = db.relationship('Manager', backref='search_history')
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'query': self.query,
            'result_count': self.result_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<SearchHistory query={self.query[:30]}... by user_id={self.user_id} manager_id={self.manager_id}>'


class SearchAnalytics(db.Model):
    """Search analytics for tracking popular searches and generating suggestions"""
    __tablename__ = 'search_analytics'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(500), nullable=False, unique=True, index=True)  # Normalized search query
    search_count = db.Column(db.Integer, default=1)  # How many times this was searched
    result_count_avg = db.Column(db.Float, default=0)  # Average result count
    last_searched_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @staticmethod
    def record_search(query, result_count=0):
        """Record a search or increment count if it exists"""
        normalized_query = query.strip().lower()
        if not normalized_query:
            return
        
        analytics = db.session.query(SearchAnalytics).filter_by(query=normalized_query).first()
        if analytics:
            # Update existing record
            analytics.search_count += 1
            analytics.last_searched_at = datetime.utcnow()
            # Update running average of result counts
            analytics.result_count_avg = (
                (analytics.result_count_avg * (analytics.search_count - 1) + result_count) / 
                analytics.search_count
            )
        else:
            # Create new record
            analytics = SearchAnalytics(
                query=normalized_query,
                search_count=1,
                result_count_avg=float(result_count),
                last_searched_at=datetime.utcnow()
            )
            db.session.add(analytics)
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error recording search analytics: {e}")
    
    @staticmethod
    def get_popular_searches(limit=10, min_results=1):
        """Get most popular searches with at least some results"""
        return db.session.query(SearchAnalytics).filter(
            SearchAnalytics.result_count_avg >= min_results
        ).order_by(
            SearchAnalytics.search_count.desc(),
            SearchAnalytics.last_searched_at.desc()
        ).limit(limit).all()
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'query': self.query,
            'search_count': self.search_count,
            'result_count_avg': self.result_count_avg,
            'last_searched_at': self.last_searched_at.isoformat() if self.last_searched_at else None
        }
    
    def __repr__(self):
        return f'<SearchAnalytics query={self.query[:30]}... count={self.search_count}>'


class Collection(db.Model):
    __tablename__ = 'collections'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_by_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(50), default='Черновик')  # Черновик, Отправлена, Просмотрена
    is_public = db.Column(db.Boolean, default=False)
    tags = db.Column(db.Text)  # JSON format: ["семейная", "премиум", "инвестиция"]
    
    # Презентация поля
    collection_type = db.Column(db.String(50), default='collection')  # 'collection' или 'presentation'
    unique_url = db.Column(db.String(100), unique=True, nullable=True)  # Уникальная ссылка для презентаций
    view_count = db.Column(db.Integer, default=0)  # Счетчик просмотров
    last_viewed_at = db.Column(db.DateTime, nullable=True)  # Последний просмотр
    client_name = db.Column(db.String(100), nullable=True)  # Имя клиента для презентации
    client_phone = db.Column(db.String(20), nullable=True)  # Телефон клиента
    presentation_notes = db.Column(db.Text, nullable=True)  # Заметки менеджера о презентации
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = db.Column(db.DateTime)
    viewed_at = db.Column(db.DateTime)
    
    # Relationships
    created_by = db.relationship('Manager', backref='created_collections')
    assigned_to = db.relationship('User', backref='received_collections')
    properties = db.relationship('CollectionProperty', backref='collection', cascade='all, delete-orphan')
    
    def generate_unique_url(self):
        """Генерирует уникальную ссылку для презентации в профессиональном формате"""
        import string
        import random
        import re
        
        # Создаем slug из названия презентации
        title_slug = ""
        if self.title:
            # Транслитерация русских символов
            translit_map = {
                'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
                'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
                'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
                'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
                ' ': '-'
            }
            
            title_slug = self.title.lower()[:30]  # Первые 30 символов
            for ru, en in translit_map.items():
                title_slug = title_slug.replace(ru, en)
            
            # Удаляем все кроме букв, цифр и дефисов
            title_slug = re.sub(r'[^\w\-]', '', title_slug)
            title_slug = re.sub(r'[-]+', '-', title_slug).strip('-')
        
        if not title_slug:
            title_slug = "presentation"
        
        # Получаем следующий порядковый номер
        max_presentations = Collection.query.filter_by(collection_type='presentation').count()
        sequence_number = str(max_presentations + 1).zfill(3)  # 001, 002, 003...
        
        # Генерируем короткий случайный код
        characters = string.ascii_lowercase + string.digits
        random_code = ''.join(random.choices(characters, k=6))
        
        # Формируем профессиональный ID в формате: title-001-abc123
        unique_code = f"{title_slug}-{sequence_number}-{random_code}"
        
        # Проверяем уникальность (на всякий случай)
        counter = 1
        original_code = unique_code
        while Collection.query.filter_by(unique_url=unique_code).first():
            unique_code = f"{original_code}-{counter}"
            counter += 1
        
        self.unique_url = unique_code
        return unique_code
    
    def increment_view_count(self):
        """Увеличивает счетчик просмотров"""
        if self.view_count is None:
            self.view_count = 0
        self.view_count += 1
        self.last_viewed_at = datetime.utcnow()
        # Убрали commit - транзакция должна контролироваться на уровне view
    
    def to_dict(self):
        """Конвертирует коллекцию в словарь"""
        try:
            # Исправлено: используем правильный доступ к relationship
            property_count = len(self.properties) if self.properties else 0
        except:
            property_count = 0
            
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'collection_type': self.collection_type,
            'unique_url': self.unique_url,
            'view_count': self.view_count,
            'client_name': self.client_name,
            'client_phone': self.client_phone,
            'status': self.status,
            'is_public': self.is_public,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_viewed_at': self.last_viewed_at.isoformat() if self.last_viewed_at else None,
            'property_count': property_count
        }
    
    def __repr__(self):
        return f'<Collection {self.title}>'


class CollectionProperty(db.Model):
    __tablename__ = 'collection_properties'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=False)
    property_id = db.Column(db.String(100), nullable=False)  # ID from properties.json
    property_inner_id = db.Column(db.String(100), nullable=True)  # Canonical inner_id from external source
    property_name = db.Column(db.String(255))
    property_price = db.Column(db.Integer)
    complex_name = db.Column(db.String(255))
    property_type = db.Column(db.String(100))
    property_size = db.Column(db.Float)
    manager_note = db.Column(db.Text)  # Комментарий менеджера к конкретной квартире
    order_index = db.Column(db.Integer, default=0)  # Порядок в подборке
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CollectionProperty {self.property_name}>'


class PresentationView(db.Model):
    """Модель для отслеживания просмотров презентаций клиентами"""
    __tablename__ = 'presentation_views'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=False)
    
    # Информация о просмотре
    view_ip = db.Column(db.String(45))  # IP адрес клиента
    user_agent = db.Column(db.Text)  # User Agent браузера
    referer = db.Column(db.String(500))  # Откуда пришел клиент
    
    # География (опционально)
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    
    # Время просмотра
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)
    view_duration = db.Column(db.Integer)  # Время на странице в секундах
    
    # Уведомления
    notification_sent = db.Column(db.Boolean, default=False)  # Отправлено ли уведомление менеджеру
    
    # Relationships
    collection = db.relationship('Collection', backref='views')
    
    def to_dict(self):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None,
            'view_duration': self.view_duration,
            'country': self.country,
            'city': self.city,
            'notification_sent': self.notification_sent
        }
    
    def __repr__(self):
        return f'<PresentationView {self.collection_id} at {self.viewed_at}>'


class ManagerNotification(db.Model):
    """Модель для уведомлений менеджеров о просмотрах презентаций и других событиях"""
    __tablename__ = 'manager_notifications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Связь с менеджером
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    
    # Информация об уведомлении
    title = db.Column(db.String(255), nullable=False)  # Заголовок уведомления
    message = db.Column(db.Text, nullable=False)  # Текст уведомления
    notification_type = db.Column(db.String(50), nullable=False, default='presentation_view')  # Тип уведомления
    
    # Статус уведомления
    is_read = db.Column(db.Boolean, default=False)  # Прочитано ли уведомление
    
    # Связь с презентацией (опционально)
    presentation_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    
    # Дополнительная информация (JSON)
    extra_data = db.Column(db.Text, nullable=True)  # Дополнительная информация в JSON формате (IP, клиент и т.д.)
    
    # Временные метки
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)  # Когда было прочитано
    
    # Relationships
    manager = db.relationship('Manager', backref='notifications')
    presentation = db.relationship('Collection', backref='notifications')
    
    def mark_as_read(self):
        """Отметить уведомление как прочитанное"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
    
    def get_extra_data(self):
        """Получить дополнительные данные как словарь"""
        import json
        try:
            if self.extra_data:
                return json.loads(self.extra_data)
            return {}
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_extra_data(self, data):
        """Установить дополнительные данные из словаря"""
        import json
        try:
            self.extra_data = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            self.extra_data = '{}'
    
    def to_dict(self):
        """Преобразовать уведомление в словарь"""
        return {
            'id': self.id,
            'manager_id': self.manager_id,
            'title': self.title,
            'message': self.message,
            'notification_type': self.notification_type,
            'is_read': self.is_read,
            'presentation_id': self.presentation_id,
            'extra_data': self.get_extra_data(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'read_at': self.read_at.isoformat() if self.read_at else None
        }
    
    def __repr__(self):
        return f'<ManagerNotification {self.notification_type} for Manager {self.manager_id}>'


class Admin(UserMixin, db.Model):
    """Administrator model with full system access"""
    __tablename__ = 'admins'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    
    # Admin specific fields
    admin_id = db.Column(db.String(20), unique=True, nullable=False)  # ADM12345678 format
    role = db.Column(db.String(50), default='Super Admin')  # Super Admin, Content Admin, Finance Admin
    permissions = db.Column(db.Text)  # JSON format permissions
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_super_admin = db.Column(db.Boolean, default=False)
    
    # Profile
    profile_image = db.Column(db.String(200), default='https://randomuser.me/api/portraits/men/1.jpg')
    phone = db.Column(db.String(20), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    last_ip = db.Column(db.String(45), nullable=True)
    last_user_agent = db.Column(db.String(500), nullable=True)
    
    def __init__(self, **kwargs):
        super(Admin, self).__init__(**kwargs)
        if not self.admin_id:
            self.admin_id = self.generate_admin_id()
        if not self.permissions:
            self.permissions = '{"all": true}'  # Default full permissions
    
    def generate_admin_id(self):
        """Generate unique admin ID in format ADM12345678"""
        import random
        while True:
            admin_id = f"ADM{random.randint(10000000, 99999999)}"
            if not Admin.query.filter_by(admin_id=admin_id).first():
                return admin_id
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, permission):
        """Check if admin has specific permission"""
        import json
        try:
            perms = json.loads(self.permissions)
            return perms.get('all', False) or perms.get(permission, False)
        except:
            return False
    
    def get_total_users(self):
        """Get total number of users"""
        return User.query.count()
    
    def get_total_managers(self):
        """Get total number of managers"""
        return Manager.query.count()
    
    def get_total_cashback_paid(self):
        """Get total cashback amount paid"""
        applications = CashbackApplication.query.filter_by(status='Выплачена').all()
        return sum(app.cashback_amount for app in applications)
    
    def get_total_cashback_approved(self):
        """Get total cashback amount approved"""
        applications = CashbackApplication.query.filter_by(status='Одобрена').all()
        return sum(app.cashback_amount for app in applications)
    
    def get_id(self):
        """Override UserMixin get_id to return prefixed ID for Flask-Login"""
        return f'a_{self.id}'
    
    def __repr__(self):
        return f'<Admin {self.email}>'


class Category(db.Model):
    """Category model for blog posts - unified system"""
    __tablename__ = 'categories'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False) 
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
    # Display settings
    icon = db.Column(db.String(50), nullable=True)  # FontAwesome icon class
    color = db.Column(db.String(20), nullable=True)  # Color scheme for UI
    sort_order = db.Column(db.Integer, default=0)    # For custom ordering
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    posts = db.relationship('BlogPost', backref='blog_category', lazy=True)
    
    def __init__(self, **kwargs):
        super(Category, self).__init__(**kwargs)
        if not self.slug and self.name:
            self.slug = self.generate_slug(self.name)
    
    def generate_slug(self, name):
        """Generate URL-friendly slug from name"""
        import re
        # Transliterate Cyrillic to Latin
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
        }
        
        slug = name.lower()
        for ru, en in translit_map.items():
            slug = slug.replace(ru, en)
        
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        slug = slug.strip('-')
        
        # Ensure uniqueness
        original_slug = slug
        counter = 1
        while Category.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        return slug
    
    def get_published_posts(self, limit=None):
        """Get published posts for this category"""
        query = BlogPost.query.filter_by(category_id=self.id, status='published')
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def __repr__(self):
        return f'<Category {self.name}>'


class BlogPost(db.Model):
    """Blog post model for content management"""
    __tablename__ = 'blog_posts'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.Text, nullable=True)
    
    # SEO fields
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    meta_keywords = db.Column(db.String(500), nullable=True)
    
    # Content management
    status = db.Column(db.String(20), default='draft')  # draft, published, archived
    featured_image = db.Column(db.String(500), nullable=True)
    
    # Category system - unified approach
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    category = db.Column(db.String(100), nullable=True)  # Keep for backward compatibility during migration
    
    tags = db.Column(db.Text, nullable=True)  # JSON array of tags
    
    # Author info
    author_id = db.Column(db.Integer, db.ForeignKey('admins.id'), nullable=False)
    author = db.relationship('Admin', backref='blog_posts')
    
    # Publishing
    published_at = db.Column(db.DateTime, nullable=True)
    scheduled_for = db.Column(db.DateTime, nullable=True)
    
    # Analytics
    views_count = db.Column(db.Integer, default=0)
    likes_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __init__(self, **kwargs):
        super(BlogPost, self).__init__(**kwargs)
        if not self.slug and self.title:
            self.slug = self.generate_slug(self.title)
    
    def generate_slug(self, title):
        """Generate URL-friendly slug from title"""
        import re
        # Transliterate Cyrillic to Latin
        translit_map = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
        }
        
        slug = title.lower()
        for ru, en in translit_map.items():
            slug = slug.replace(ru, en)
        
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        slug = slug.strip('-')
        
        # Ensure uniqueness
        original_slug = slug
        counter = 1
        while BlogPost.query.filter_by(slug=slug).first():
            slug = f"{original_slug}-{counter}"
            counter += 1
        
        return slug
    
    def publish(self):
        """Publish the blog post"""
        self.status = 'published'
        self.published_at = datetime.utcnow()
        db.session.commit()
    
    def unpublish(self):
        """Unpublish the blog post"""
        self.status = 'draft'
        self.published_at = None
        db.session.commit()
    
    def increment_views(self):
        """Increment view count"""
        self.views_count += 1
        db.session.commit()
    
    def __repr__(self):
        return f'<BlogPost {self.title}>'

class CashbackApplication(db.Model):
    __tablename__ = 'cashback_applications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.String(50), nullable=True)  # Property ID from JSON data
    property_name = db.Column(db.String(200), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)  # 1-комн, 2-комн, студия
    property_size = db.Column(db.Float, nullable=False)  # площадь в м²
    property_price = db.Column(db.Integer, nullable=False)  # цена в рублях
    complex_name = db.Column(db.String(200), nullable=False)
    developer_name = db.Column(db.String(200), nullable=False)
    cashback_amount = db.Column(db.Integer, nullable=False)  # сумма кешбека в рублях
    cashback_percent = db.Column(db.Float, nullable=False)  # процент кешбека
    status = db.Column(db.String(50), default='На рассмотрении')  # На рассмотрении, Одобрена, Отклонена, Выплачена
    application_date = db.Column(db.DateTime, default=datetime.utcnow)
    approved_date = db.Column(db.DateTime)
    payout_date = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    
    # Manager fields
    approved_by_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    manager_notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='cashback_applications')
    approved_by_manager = db.relationship('Manager', foreign_keys=[approved_by_manager_id])

class FavoriteProperty(db.Model):
    __tablename__ = 'favorite_properties'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.String(50), nullable=True)  # Property ID from JSON data
    property_name = db.Column(db.String(200), nullable=False)
    property_type = db.Column(db.String(50), nullable=True)
    property_size = db.Column(db.Float, nullable=True)
    property_price = db.Column(db.Integer, nullable=True)
    complex_name = db.Column(db.String(200), nullable=True)
    developer_name = db.Column(db.String(200), nullable=True)
    property_image = db.Column(db.String(500))
    property_url = db.Column(db.String(500))
    cashback_amount = db.Column(db.Integer)
    cashback_percent = db.Column(db.Float)
    viewed = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='favorite_properties')


class FavoriteComplex(db.Model):
    __tablename__ = 'favorite_complexes'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    complex_id = db.Column(db.String(50), nullable=True)  # Complex ID from JSON data
    complex_name = db.Column(db.String(200), nullable=False)
    developer_name = db.Column(db.String(200), nullable=True)
    complex_address = db.Column(db.String(500), nullable=True)
    district = db.Column(db.String(100), nullable=True)
    min_price = db.Column(db.Integer, nullable=True)
    max_price = db.Column(db.Integer, nullable=True)
    complex_image = db.Column(db.String(500))
    complex_url = db.Column(db.String(500))
    status = db.Column(db.String(50), nullable=True)  # В продаже, Построен, Строится
    viewed = db.Column(db.Boolean, default=False, nullable=False)  # Viewed status
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='favorite_complexes')

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'complex_id': self.complex_id,
            'complex_name': self.complex_name,
            'developer_name': self.developer_name,
            'complex_address': self.complex_address,
            'district': self.district,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'complex_image': self.complex_image,
            'complex_url': self.complex_url,
            'status': self.status,
            'created_at': self.created_at.strftime('%d.%m.%Y в %H:%M') if self.created_at else None
        }

class ManagerFavoriteProperty(db.Model):
    """Manager's favorite properties for client recommendations"""
    __tablename__ = 'manager_favorite_properties'
    __table_args__ = (
        db.UniqueConstraint('manager_id', 'property_id', name='unique_manager_property_favorite'),
        db.Index('idx_manager_favorite_properties_manager', 'manager_id'),
        db.Index('idx_manager_favorite_properties_property', 'property_id'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    property_id = db.Column(db.String(50), nullable=True)  # Property ID from JSON data
    property_name = db.Column(db.String(200), nullable=False)
    property_type = db.Column(db.String(50), nullable=True)
    property_size = db.Column(db.Float, nullable=True)
    property_price = db.Column(db.Integer, nullable=True)
    complex_name = db.Column(db.String(200), nullable=True)
    developer_name = db.Column(db.String(200), nullable=True)
    property_image = db.Column(db.String(500))
    property_url = db.Column(db.String(500))
    cashback_amount = db.Column(db.Integer)
    cashback_percent = db.Column(db.Float)
    
    # Manager-specific fields
    notes = db.Column(db.Text)  # Manager's notes about this property
    recommended_for = db.Column(db.String(200))  # Type of clients this is good for
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    manager = db.relationship('Manager', backref='favorite_properties')

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'property_id': self.property_id,
            'property_name': self.property_name,
            'property_type': self.property_type,
            'property_size': self.property_size,
            'property_price': self.property_price,
            'complex_name': self.complex_name,
            'developer_name': self.developer_name,
            'property_image': self.property_image,
            'property_url': self.property_url,
            'cashback_amount': self.cashback_amount,
            'cashback_percent': self.cashback_percent,
            'notes': self.notes,
            'recommended_for': self.recommended_for,
            'created_at': self.created_at.strftime('%d.%m.%Y в %H:%M') if self.created_at else None
        }


class ManagerFavoriteComplex(db.Model):
    """Manager's favorite complexes for client recommendations"""
    __tablename__ = 'manager_favorite_complexes'
    __table_args__ = (
        db.UniqueConstraint('manager_id', 'complex_id', name='unique_manager_complex_favorite'),
        db.Index('idx_manager_favorite_complexes_manager', 'manager_id'),
        db.Index('idx_manager_favorite_complexes_complex', 'complex_id'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    complex_id = db.Column(db.String(50), nullable=True)  # Complex ID from JSON data
    complex_name = db.Column(db.String(200), nullable=False)
    developer_name = db.Column(db.String(200), nullable=True)
    complex_address = db.Column(db.String(500), nullable=True)
    district = db.Column(db.String(100), nullable=True)
    min_price = db.Column(db.Integer, nullable=True)
    max_price = db.Column(db.Integer, nullable=True)
    complex_image = db.Column(db.String(500))
    complex_url = db.Column(db.String(500))
    status = db.Column(db.String(50), nullable=True)  # В продаже, Построен, Строится
    object_class_display_name = db.Column(db.String(100), nullable=True)  # Класс жилья (эконом, комфорт, бизнес)
    
    # Manager-specific fields
    notes = db.Column(db.Text)  # Manager's notes about this complex
    recommended_for = db.Column(db.String(200))  # Type of clients this is good for
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    manager = db.relationship('Manager', backref='favorite_complexes')

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'complex_id': self.complex_id,
            'complex_name': self.complex_name,
            'developer_name': self.developer_name,
            'complex_address': self.complex_address,
            'district': self.district,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'complex_image': self.complex_image,
            'complex_url': self.complex_url,
            'status': self.status,
            'object_class_display_name': self.object_class_display_name,
            'notes': self.notes,
            'recommended_for': self.recommended_for,
            'created_at': self.created_at.strftime('%d.%m.%Y в %H:%M') if self.created_at else None
        }


class Document(db.Model):
    __tablename__ = 'documents'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # pdf, doc, docx, jpg, png
    file_size = db.Column(db.Integer, nullable=False)  # размер в байтах
    file_path = db.Column(db.String(500), nullable=False)
    document_type = db.Column(db.String(100))  # паспорт, справка о доходах, и т.д.
    status = db.Column(db.String(50), default='На проверке')  # На проверке, Проверен, Отклонен
    reviewed_at = db.Column(db.DateTime)
    reviewer_notes = db.Column(db.Text)
    reviewed_by_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='documents')
    reviewed_by_manager = db.relationship('Manager', foreign_keys=[reviewed_by_manager_id])


class SavedSearch(db.Model):
    """User's saved search parameters"""
    __tablename__ = 'saved_searches'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=True)  # City where search was saved
    name = db.Column(db.String(100), nullable=False)  # User-defined name for the search
    description = db.Column(db.Text)  # Optional description
    
    # Search parameters
    search_type = db.Column(db.String(20), default='properties')  # 'properties' or 'complexes'
    location = db.Column(db.String(200))  # District, street, etc.
    property_type = db.Column(db.String(50))  # 1-комн, 2-комн, etc.
    price_min = db.Column(db.Integer)
    price_max = db.Column(db.Integer)
    size_min = db.Column(db.Float)
    size_max = db.Column(db.Float)
    developer = db.Column(db.String(200))
    complex_name = db.Column(db.String(200))
    floor_min = db.Column(db.Integer)
    floor_max = db.Column(db.Integer)
    cashback_min = db.Column(db.Integer)
    
    # Additional filters (JSON format for flexibility)
    additional_filters = db.Column(db.Text)  # JSON string with any other filters
    
    # Search settings
    notify_new_matches = db.Column(db.Boolean, default=True)  # Notify when new properties match
    last_notification_sent = db.Column(db.DateTime)
    created_from_quiz = db.Column(db.Boolean, default=False)  # Created from registration quiz
    
    # Alert settings (Zillow/Rightmove style)
    alert_enabled = db.Column(db.Boolean, default=True)  # Master switch for alerts
    alert_frequency = db.Column(db.String(20), default='weekly')  # instant, daily, weekly, never
    alert_channels = db.Column(db.Text, default='["email"]')  # JSON array: email, telegram, push
    last_alert_sent = db.Column(db.DateTime)  # Last time any alert was sent
    alert_count_today = db.Column(db.Integer, default=0)  # For rate limiting (15/day instant)
    alert_count_reset_date = db.Column(db.Date)  # Track when to reset daily counter
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='saved_searches')
    
    def to_dict(self):
        """Convert search to dictionary for easy JSON serialization"""
        import json
        
        # Parse additional_filters from JSON string to dict
        filters_dict = {}
        if self.additional_filters:
            try:
                filters_dict = json.loads(self.additional_filters)
            except:
                pass
        
        # Parse alert_channels from JSON
        channels_list = ['email']  # default
        if self.alert_channels:
            try:
                channels_list = json.loads(self.alert_channels)
            except:
                pass
        
        # Get city slug if city_id is set
        city_slug = None
        city_name = None
        if hasattr(self, 'city_id') and self.city_id:
            from models import City
            city = City.query.get(self.city_id)
            if city:
                city_slug = city.slug
                city_name = city.name
        
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'city_id': self.city_id if hasattr(self, 'city_id') else None,
            'city_slug': city_slug,
            'city': city_slug,  # Alias for JS compatibility
            'city_name': city_name,
            'search_type': self.search_type,
            'location': self.location,
            'property_type': self.property_type,
            'price_min': self.price_min,
            'price_max': self.price_max,
            'size_min': self.size_min,
            'size_max': self.size_max,
            'developer': self.developer,
            'complex_name': self.complex_name,
            'floor_min': self.floor_min,
            'floor_max': self.floor_max,
            'cashback_min': self.cashback_min,
            'additional_filters': self.additional_filters,
            'filters': filters_dict,  # Add parsed filters for UI
            'notify_new_matches': self.notify_new_matches,
            'alert_enabled': self.alert_enabled if hasattr(self, 'alert_enabled') else True,
            'alert_frequency': self.alert_frequency if hasattr(self, 'alert_frequency') else 'weekly',
            'alert_channels': channels_list,
            'last_alert_sent': self.last_alert_sent.strftime('%d.%m.%Y в %H:%M') if (hasattr(self, 'last_alert_sent') and self.last_alert_sent) else None,
            'created_at': self.created_at.strftime('%d.%m.%Y в %H:%M') if self.created_at else None,
            'last_used': self.last_used.strftime('%d.%m.%Y в %H:%M') if self.last_used else None
        }
    
    def __repr__(self):
        return f'<SavedSearch {self.name}>'

class ManagerSavedSearch(db.Model):
    """Manager's saved search parameters for sending to clients"""
    __tablename__ = 'manager_saved_searches'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # Manager-defined name for the search
    description = db.Column(db.Text)  # Optional description
    
    # Search parameters (same structure as SavedSearch for compatibility)
    search_type = db.Column(db.String(20), default='properties')  # 'properties' or 'complexes'
    location = db.Column(db.String(200))  # District, street, etc.
    property_type = db.Column(db.String(50))  # 1-комн, 2-комн, etc.
    price_min = db.Column(db.Integer)
    price_max = db.Column(db.Integer)
    size_min = db.Column(db.Float)
    size_max = db.Column(db.Float)
    developer = db.Column(db.String(200))
    complex_name = db.Column(db.String(200))
    floor_min = db.Column(db.Integer)
    floor_max = db.Column(db.Integer)
    cashback_min = db.Column(db.Integer)
    
    # Additional filters (JSON format for flexibility) 
    additional_filters = db.Column(db.Text)  # JSON string with any other filters
    
    # Manager-specific fields
    is_template = db.Column(db.Boolean, default=False)  # Whether this can be used as template
    usage_count = db.Column(db.Integer, default=0)  # How many times sent to clients
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Manager', backref='saved_searches')
    
    def to_dict(self):
        """Convert search to dictionary for easy JSON serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'search_type': self.search_type,
            'location': self.location,
            'property_type': self.property_type,
            'price_min': self.price_min,
            'price_max': self.price_max,
            'size_min': self.size_min,
            'size_max': self.size_max,
            'developer': self.developer,
            'complex_name': self.complex_name,
            'floor_min': self.floor_min,
            'floor_max': self.floor_max,
            'cashback_min': self.cashback_min,
            'additional_filters': self.additional_filters,
            'is_template': self.is_template,
            'usage_count': self.usage_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used': self.last_used.isoformat() if self.last_used else None
        }
    
    def __repr__(self):
        return f'<ManagerSavedSearch {self.name}>'

class SentSearch(db.Model):
    """Record of searches sent from managers to clients"""
    __tablename__ = 'sent_searches'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    manager_search_id = db.Column(db.Integer, db.ForeignKey('manager_saved_searches.id'), nullable=True)
    
    # Copy of search parameters at time of sending (for history)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    additional_filters = db.Column(db.Text)  # JSON string with filters
    
    # Status tracking
    status = db.Column(db.String(20), default='sent')  # sent, viewed, applied, expired
    viewed_at = db.Column(db.DateTime)
    applied_at = db.Column(db.DateTime) 
    expires_at = db.Column(db.DateTime)  # Optional expiration
    
    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Manager', backref='sent_searches')
    client = db.relationship('User', backref='received_searches')
    manager_search = db.relationship('ManagerSavedSearch', backref='sent_instances')
    
    def __repr__(self):
        return f'<SentSearch {self.name} from Manager {self.manager_id} to User {self.client_id}>'

class UserNotification(db.Model):
    __tablename__ = 'user_notifications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default='info')  # info, success, warning, error
    icon = db.Column(db.String(50), default='fas fa-info-circle')
    is_read = db.Column(db.Boolean, default=False)
    action_url = db.Column(db.String(500))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='user_notifications')


class PropertyAlert(db.Model):
    """Track property alerts sent to users for saved searches"""
    __tablename__ = 'property_alerts'
    __table_args__ = (
        db.UniqueConstraint('saved_search_id', 'property_id', 'alert_type', name='unique_alert_per_property'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    saved_search_id = db.Column(db.Integer, db.ForeignKey('saved_searches.id'), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Denormalized for quick lookup
    
    # Alert details
    alert_type = db.Column(db.String(20), nullable=False)  # NEW_LISTING, PRICE_DROP, STATUS_CHANGE
    alert_frequency = db.Column(db.String(20), nullable=False)  # instant, daily, weekly (snapshot at send time)
    
    # Property snapshot (prices can change)
    property_price_at_send = db.Column(db.Integer)
    price_drop_amount = db.Column(db.Integer)  # If PRICE_DROP, how much it dropped
    price_drop_percentage = db.Column(db.Float)  # If PRICE_DROP, percentage
    
    # Delivery tracking
    delivery_channel = db.Column(db.String(20), nullable=False)  # email, telegram, push
    delivery_status = db.Column(db.String(20), default='sent')  # sent, delivered, failed, bounced
    delivery_error = db.Column(db.Text)  # Error message if failed
    
    # Engagement tracking
    email_opened = db.Column(db.Boolean, default=False)
    email_clicked = db.Column(db.Boolean, default=False)
    opened_at = db.Column(db.DateTime)
    clicked_at = db.Column(db.DateTime)
    
    # Timestamps
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    saved_search = db.relationship('SavedSearch', backref='sent_alerts')
    property = db.relationship('Property', backref='alerts_sent')
    user = db.relationship('User', backref='property_alerts')
    
    def to_dict(self):
        return {
            'id': self.id,
            'alert_type': self.alert_type,
            'property_id': self.property_id,
            'price_at_send': self.property_price_at_send,
            'price_drop': self.price_drop_amount,
            'delivery_channel': self.delivery_channel,
            'delivery_status': self.delivery_status,
            'sent_at': self.sent_at.strftime('%d.%m.%Y в %H:%M') if self.sent_at else None,
            'opened': self.email_opened,
            'clicked': self.email_clicked
        }
    
    def __repr__(self):
        return f'<PropertyAlert {self.alert_type} for Property {self.property_id}>'


class CashbackRecord(db.Model):
    """Cashback record model"""
    __tablename__ = 'cashback_records'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Property details
    property_id = db.Column(db.Integer, nullable=True)  # Reference to property
    property_name = db.Column(db.String(200), nullable=False)
    property_price = db.Column(db.Float, nullable=False)
    
    # Cashback details
    amount = db.Column(db.Float, nullable=False)
    percentage = db.Column(db.Float, nullable=False)  # 2.5, 3.0, etc.
    status = db.Column(db.String(20), default='pending')  # pending, approved, paid, rejected
    
    # Dates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<CashbackRecord {self.property_name}: {self.amount}₽>'


class Application(db.Model):
    """User application model"""
    __tablename__ = 'applications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Allow null for anonymous applications
    
    # Contact information for anonymous applications
    contact_name = db.Column(db.String(200), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    
    # Application details
    property_id = db.Column(db.String(50), nullable=True)  # Changed to match other models
    property_name = db.Column(db.String(200), nullable=False)
    complex_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='new')  # new, in_progress, approved, rejected, completed
    
    # Contact info
    message = db.Column(db.Text, nullable=True)
    preferred_contact = db.Column(db.String(20), default='email')  # phone, email, telegram, both
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Application {self.property_name}>'


class Favorite(db.Model):
    """User favorites model"""
    __tablename__ = 'favorites'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    property_id = db.Column(db.Integer, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'property_id', name='unique_user_property'),)
    
    def __repr__(self):
        return f'<Favorite user:{self.user_id} property:{self.property_id}>'


class Notification(db.Model):
    """User notifications model"""
    __tablename__ = 'notifications'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Notification details
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')  # info, success, warning, error
    icon = db.Column(db.String(50), default='fas fa-info-circle')
    
    # Status
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref='notifications', lazy=True)
    
    def __repr__(self):
        return f'<Notification {self.title}>'

class ClientPropertyRecommendation(db.Model):
    """Model for manager-to-client property recommendations"""
    __tablename__ = 'client_property_recommendations'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Manager who sent
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)   # Client who receives
    search_id = db.Column(db.Integer, db.ForeignKey('saved_searches.id'), nullable=False)  # Search being shared
    message = db.Column(db.Text)  # Personal message from manager
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    viewed_at = db.Column(db.DateTime)
    
    # Relationships
    manager = db.relationship('User', foreign_keys=[manager_id], backref='sent_property_recommendations')
    client = db.relationship('User', foreign_keys=[client_id], backref='received_property_recommendations')
    search = db.relationship('SavedSearch', backref='property_recommendations')
    
    def to_dict(self):
        return {
            'id': self.id,
            'manager': {
                'id': self.manager.id,
                'full_name': self.manager.full_name,
                'email': self.manager.email
            },
            'client': {
                'id': self.client.id,
                'full_name': self.client.full_name,
                'email': self.client.email
            },
            'search': self.search.to_dict(),
            'message': self.message,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None
        }


class SearchCategory(db.Model):
    """Search categories for autocomplete"""
    __tablename__ = 'search_categories'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_type = db.Column(db.String(50), nullable=False)  # district, developer, complex, rooms, street
    slug = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class District(db.Model):
    """Districts within cities (multi-city support)"""
    __tablename__ = 'districts'
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_district_slug_per_city'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    
    # Multi-city support: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='districts')
    
    # District type: 'admin' for administrative districts, 'micro' for microdistricts
    district_type = db.Column(db.String(10), default='micro', nullable=False)
    
    # Coordinates for map display
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Map zoom level for district view
    zoom_level = db.Column(db.Integer, default=13)
    
    # Distance to city center (will be calculated per city, not just Krasnodar)
    distance_to_center = db.Column(db.Float, nullable=True)
    
    # Infrastructure data as JSON string
    infrastructure_data = db.Column(db.Text, nullable=True)
    
    # District boundary geometry (from OSM/Yandex/Kayan)
    geometry = db.Column(db.Text, nullable=True)  # Format: lat1,lng1;lat2,lng2;...
    geometry_source = db.Column(db.String(50), nullable=True)  # osm, yandex, kayan
    
    # SEO and additional info
    description = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResidentialComplex(db.Model):
    """Residential complexes (multi-city support)"""
    __tablename__ = 'residential_complexes'
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_complex_slug_per_city'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    
    # Multi-city support: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='residential_complexes')
    
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'))
    cashback_rate = db.Column(db.Float, default=5.0, nullable=False)
    
    # Complex type: 'residential' (Жилой комплекс) or 'cottage' (Коттеджный поселок)
    complex_type = db.Column(db.String(20), default='residential', nullable=False)
    
    # Parser data fields
    complex_id = db.Column(db.String(50), nullable=True)  # external ID from parser
    complex_phone = db.Column(db.String(20), nullable=True)
    sales_phone = db.Column(db.String(20), nullable=True)
    sales_address = db.Column(db.String(300), nullable=True)
    object_class_id = db.Column(db.String(50), nullable=True)
    object_class_display_name = db.Column(db.String(100), nullable=True)
    
    # Construction dates
    start_build_year = db.Column(db.Integer, nullable=True)
    start_build_quarter = db.Column(db.Integer, nullable=True)
    first_build_year = db.Column(db.Integer, nullable=True)
    first_build_quarter = db.Column(db.Integer, nullable=True)
    end_build_year = db.Column(db.Integer, nullable=True)
    end_build_quarter = db.Column(db.Integer, nullable=True)
    
    # Features
    has_accreditation = db.Column(db.Boolean, default=False)
    has_green_mortgage = db.Column(db.Boolean, default=False)
    has_big_check = db.Column(db.Boolean, default=False)
    with_renovation = db.Column(db.Boolean, default=False)
    financing_sber = db.Column(db.Boolean, default=False)
    
    # Status and limits
    is_active = db.Column(db.Boolean, default=True)
    max_cashback_amount = db.Column(db.Integer, nullable=True)  # Maximum cashback amount in rubles
    
    # Images and media
    main_image = db.Column(db.String(500), nullable=True)  # Main complex image
    gallery_images = db.Column(db.Text, nullable=True)  # JSON array of image URLs
    
    # Location
    latitude = db.Column(db.Float, nullable=True)  # Complex center latitude
    longitude = db.Column(db.Float, nullable=True)  # Complex center longitude
    address = db.Column(db.String(500), nullable=True)  # Full address
    
    # Description and media
    description = db.Column(db.Text, nullable=True)  # Complex description
    detailed_description = db.Column(db.Text, nullable=True)  # Detailed complex description
    video_url = db.Column(db.String(500), nullable=True)  # DEPRECATED: Legacy single video URL (use videos instead)
    videos = db.Column(db.Text, nullable=True)  # JSON array of videos: [{"type": "youtube", "url": "...", "title": "..."}]
    uploaded_video = db.Column(db.String(500), nullable=True)  # Path to uploaded video file
    amenities = db.Column(db.Text, nullable=True)  # JSON array of amenities/features
    construction_photos_updated_at = db.Column(db.DateTime, nullable=True)  # Last update date for construction photos
    infrastructure = db.Column(db.Text, nullable=True)  # Infrastructure description
    buildings_count = db.Column(db.Integer, default=0)  # Number of buildings in complex
    construction_progress_images = db.Column(db.Text, nullable=True)  # JSON array of construction progress photos
    
    # Additional features and information
    nearby = db.Column(db.Text, nullable=True)  # What's nearby (schools, parks, shops, etc.)
    nearby_updated_at = db.Column(db.DateTime, nullable=True)  # Last update date for nearby places data
    advantages = db.Column(db.Text, nullable=True)  # JSON array of advantages/benefits
    ceiling_height = db.Column(db.String(50), nullable=True)  # Ceiling height (e.g., "от 3.2 м")
    wall_material = db.Column(db.String(100), nullable=True)  # Материал стен (монолит, кирпич, панель)
    finishing_type = db.Column(db.String(100), nullable=True)  # Отделка (предчистовая, чистовая и т.д.)
    parking_type = db.Column(db.String(100), nullable=True)    # Тип парковки (подземная, гостевая и т.д.)
    floors_min = db.Column(db.Integer, nullable=True)          # Минимальная этажность корпусов
    floors_max = db.Column(db.Integer, nullable=True)          # Максимальная этажность корпусов
    logo_url = db.Column(db.String(400), nullable=True)        # Логотип застройщика/ЖК
    finishing_variants = db.Column(db.Text, nullable=True)     # JSON: варианты отделки от застройщика
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    district = db.relationship('District', backref='complexes')
    developer = db.relationship('Developer', backref='complexes')
    buildings = db.relationship('Building', backref='residential_complex', cascade='all, delete-orphan')


class Building(db.Model):
    """Buildings/Korpus/Liter within residential complexes"""
    __tablename__ = 'buildings'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # "Корпус 1", "Литер А"
    slug = db.Column(db.String(100), nullable=False)
    
    # Relations
    complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=False)
    
    # Parser data
    building_id = db.Column(db.String(50), nullable=True)  # external ID from parser
    building_name = db.Column(db.String(100), nullable=True)  # original name from parser
    released = db.Column(db.Boolean, default=False)
    is_unsafe = db.Column(db.Boolean, default=False)
    has_accreditation = db.Column(db.Boolean, default=False)
    has_green_mortgage = db.Column(db.Boolean, default=False)
    
    # Construction dates
    end_build_year = db.Column(db.Integer, nullable=True)
    end_build_quarter = db.Column(db.Integer, nullable=True)
    
    # Additional info
    complex_product = db.Column(db.String(100), nullable=True)  # тип продукта
    
    # Statistics
    total_floors = db.Column(db.Integer, nullable=True)
    total_apartments = db.Column(db.Integer, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships  
    properties = db.relationship('Property', backref='building', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Building {self.name}>'


class Street(db.Model):
    """Streets within cities (multi-city support)"""
    __tablename__ = 'streets'
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_street_slug_per_city'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False)
    
    # Multi-city support: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='streets')
    
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'))
    district = db.relationship('District', backref='streets')
    
    # Coordinates for map display  
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Map zoom level for street view
    zoom_level = db.Column(db.Integer, default=15)
    
    # Street geometry (polyline coordinates for highlighting on map)
    # Format: "lat1,lng1;lat2,lng2;lat3,lng3" for LineString
    # Multiple segments separated by "#": "segment1#segment2#segment3"
    geometry = db.Column(db.Text, nullable=True)
    geometry_source = db.Column(db.String(20), nullable=True)  # 'osm', 'yandex', 'manual'
    
    # Street type (улица, проспект, переулок, etc.)
    street_type = db.Column(db.String(20), nullable=True)
    
    # SEO and additional info
    description = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RoomType(db.Model):
    """Room types for apartments"""
    __tablename__ = 'room_types'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # "1-комнатная", "2-комнатная", "студия"
    rooms_count = db.Column(db.Integer)

class CashbackPayout(db.Model):
    """Model for cashback payout requests"""
    __tablename__ = 'cashback_payouts'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    status = db.Column(db.String(50), default='Запрошена')  # Запрошена, Одобрена, Выплачена, Отклонена
    payment_method = db.Column(db.String(100), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    user = db.relationship('User', backref='cashback_payouts')
    
    def __repr__(self):
        return f'<CashbackPayout {self.id}: {self.amount} ₽>'

class RecommendationCategory(db.Model):
    """Categories for organizing recommendations by client and manager"""
    __tablename__ = 'recommendation_categories'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # e.g., "Однокомнатные до 5 млн, Черемушки"
    description = db.Column(db.Text)  # Optional description
    
    # Ownership
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Category settings
    color = db.Column(db.String(20), default='blue')  # Color theme for UI
    is_active = db.Column(db.Boolean, default=True)
    filters = db.Column(db.Text, nullable=True)  # JSON string of filter criteria
    
    # Statistics
    recommendations_count = db.Column(db.Integer, default=0)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Manager', backref='recommendation_categories')
    client = db.relationship('User', backref='recommendation_categories')
    recommendations = db.relationship('Recommendation', backref='category', lazy=True)
    
    def __repr__(self):
        return f'<RecommendationCategory {self.name} for {self.client.full_name}>'

class Recommendation(db.Model):
    """Manager recommendations to clients - properties or complexes"""
    __tablename__ = 'recommendations'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('recommendation_categories.id'), nullable=True)
    
    # Recommendation details
    title = db.Column(db.String(255), nullable=False)  # Custom title from manager
    description = db.Column(db.Text)  # Manager's personal note/recommendation
    recommendation_type = db.Column(db.String(20), nullable=False)  # 'property' or 'complex'
    
    # Item details (property or complex)
    item_id = db.Column(db.String(100), nullable=False)  # Property ID or complex ID from JSON
    item_name = db.Column(db.String(255), nullable=False)  # Property/complex name
    item_data = db.Column(db.Text)  # JSON with full item details for history
    
    # Manager notes and highlights
    manager_notes = db.Column(db.Text)  # Why recommended
    highlighted_features = db.Column(db.Text)  # JSON array of key features to highlight
    priority_level = db.Column(db.String(20), default='normal')  # urgent, high, normal, low
    
    # Status tracking
    status = db.Column(db.String(20), default='sent')  # sent, viewed, interested, not_interested, scheduled_viewing
    viewed_at = db.Column(db.DateTime)
    responded_at = db.Column(db.DateTime)  # When client responded
    client_response = db.Column(db.String(20))  # interested, not_interested, need_more_info
    client_notes = db.Column(db.Text)  # Client's feedback
    
    # Scheduling
    viewing_requested = db.Column(db.Boolean, default=False)
    viewing_scheduled_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)  # Optional expiration for offer
    
    # Relationships
    manager = db.relationship('Manager', backref='sent_recommendations')
    client = db.relationship('User', backref='received_recommendations')
    
    def to_dict(self):
        """Convert recommendation to dictionary"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'recommendation_type': self.recommendation_type,
            'item_id': self.item_id,
            'item_name': self.item_name,
            'manager_notes': self.manager_notes,
            'priority_level': self.priority_level,
            'status': self.status,
            'client_response': self.client_response,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None,
            'highlighted_features': self.highlighted_features,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'client_notes': self.client_notes,
            'viewing_requested': self.viewing_requested,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None,
            'viewing_scheduled_at': self.viewing_scheduled_at.isoformat() if self.viewing_scheduled_at else None
        }
    
    def __repr__(self):
        return f'<Recommendation {self.title} from Manager {self.manager_id} to User {self.client_id}>'

class RecommendationTemplate(db.Model):
    """Templates for common recommendations that managers can reuse"""
    __tablename__ = 'recommendation_templates'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    
    # Template details
    name = db.Column(db.String(255), nullable=False)  # Template name
    description = db.Column(db.Text)  # Template description
    recommendation_type = db.Column(db.String(20), nullable=False)  # 'property' or 'complex'
    
    # Default content
    default_title = db.Column(db.String(255))
    default_description = db.Column(db.Text)
    default_notes = db.Column(db.Text)
    default_highlighted_features = db.Column(db.Text)  # JSON array
    default_priority = db.Column(db.String(20), default='normal')
    
    # Template settings
    is_active = db.Column(db.Boolean, default=True)
    usage_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used = db.Column(db.DateTime)
    
    # Relationships
    manager = db.relationship('Manager', backref='recommendation_templates')
    
    def __repr__(self):
        return f'<RecommendationTemplate {self.name}>'


class BlogCategory(db.Model):
    """Blog categories for organizing articles"""
    __tablename__ = 'blog_categories'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='blue')
    icon = db.Column(db.String(50))  # FontAwesome icon class
    
    # SEO
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.String(300))
    
    # Ordering and visibility
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    # Statistics
    articles_count = db.Column(db.Integer, default=0)
    views_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    articles = db.relationship('BlogArticle', backref='category', lazy=True)
    
    def __repr__(self):
        return f'<BlogCategory {self.name}>'


class BlogArticle(db.Model):
    """Blog articles with full content management"""
    __tablename__ = 'blog_articles'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True)
    excerpt = db.Column(db.String(500))  # Short description
    content = db.Column(db.Text, nullable=False)  # Full HTML content
    
    # Author info
    author_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    author_name = db.Column(db.String(100))  # Override author display name
    
    # Category
    category_id = db.Column(db.Integer, db.ForeignKey('blog_categories.id'), nullable=False)
    
    # Publishing
    status = db.Column(db.String(20), default='draft')  # draft, published, scheduled, archived
    published_at = db.Column(db.DateTime)
    scheduled_at = db.Column(db.DateTime)  # For scheduled publishing
    
    # SEO and meta
    meta_title = db.Column(db.String(200))
    meta_description = db.Column(db.String(300))
    meta_keywords = db.Column(db.String(500))
    featured_image = db.Column(db.String(300))  # URL to featured image
    featured_image_alt = db.Column(db.String(200))
    
    # Content settings
    is_featured = db.Column(db.Boolean, default=False)
    allow_comments = db.Column(db.Boolean, default=True)
    
    # Statistics
    views_count = db.Column(db.Integer, default=0)
    reading_time = db.Column(db.Integer, default=0)  # Estimated reading time in minutes
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    author = db.relationship('Manager', backref='blog_articles')
    comments = db.relationship('BlogComment', backref='article', lazy=True, cascade='all, delete-orphan')
    tags = db.relationship('BlogTag', secondary='blog_article_tags', backref='articles')
    
    def __repr__(self):
        return f'<BlogArticle {self.title}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'slug': self.slug,
            'excerpt': self.excerpt,
            'content': self.content,
            'status': self.status,
            'category': {
                'id': self.category.id,
                'name': self.category.name,
                'slug': self.category.slug
            },
            'author': {
                'id': self.author.id,
                'name': self.author_name or self.author.full_name
            },
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'views_count': self.views_count,
            'reading_time': self.reading_time,
            'featured_image': self.featured_image,
            'is_featured': self.is_featured
        }


class BlogTag(db.Model):
    """Tags for blog articles"""
    __tablename__ = 'blog_tags'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    slug = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    
    # Statistics
    usage_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<BlogTag {self.name}>'


# Association table for many-to-many relationship between articles and tags
blog_article_tags = db.Table('blog_article_tags',
    db.Column('article_id', db.Integer, db.ForeignKey('blog_articles.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('blog_tags.id'), primary_key=True)
)


class BlogComment(db.Model):
    """Comments on blog articles"""
    __tablename__ = 'blog_comments'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('blog_articles.id'), nullable=False)
    
    # Author info
    author_name = db.Column(db.String(100), nullable=False)
    author_email = db.Column(db.String(120), nullable=False)
    author_website = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # If registered user
    
    # Comment content
    content = db.Column(db.Text, nullable=False)
    
    # Moderation
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, spam
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(300))
    
    # Threading support
    parent_id = db.Column(db.Integer, db.ForeignKey('blog_comments.id'))
    parent = db.relationship('BlogComment', remote_side=[id], backref='replies')
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='blog_comments')
    
    def __repr__(self):
        return f'<BlogComment by {self.author_name}>'

class Property(db.Model):
    """Property/Apartment model for real estate listings (multi-city support)"""
    __tablename__ = 'properties'
    __table_args__ = (
        db.UniqueConstraint('city_id', 'slug', name='unique_property_slug_per_city'),
        db.Index('idx_property_city_active', 'city_id', 'is_active'),
        db.Index('idx_property_developer_active', 'developer_id', 'is_active'),
        db.Index('idx_property_complex_active', 'complex_id', 'is_active'),
        db.Index('idx_property_district_active', 'district_id', 'is_active'),
        db.Index('idx_property_price', 'price'),
        db.Index('idx_property_rooms', 'rooms'),
        db.Index('idx_property_inner_id', 'inner_id'),
        db.Index('idx_property_active_price', 'is_active', 'price'),
        db.Index('idx_property_city_rooms_active', 'city_id', 'rooms', 'is_active'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic property information
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    
    # Property details
    rooms = db.Column(db.Integer, nullable=True)  # Количество комнат (0 для студии)
    area = db.Column(db.Float, nullable=True)  # Площадь в м²
    floor = db.Column(db.Integer, nullable=True)  # Этаж
    total_floors = db.Column(db.Integer, nullable=True)  # Всего этажей в доме
    
    # Pricing
    price = db.Column(db.Integer, nullable=True)  # Цена в рублях
    price_per_sqm = db.Column(db.Integer, nullable=True)  # Цена за м²
    
    # Location and relations
    # Multi-city support: Foreign key to City
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='properties')
    
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'), nullable=True)
    complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=True)  # Правильное имя поля из БД
    building_id = db.Column(db.Integer, db.ForeignKey('buildings.id'), nullable=True)  # new field for hierarchy
    complex_building_name = db.Column(db.String(100), nullable=True)  # Building name (e.g. "Корпус 1", "Литер 7")
    district_id = db.Column(db.Integer, db.ForeignKey('districts.id'), nullable=True)
    
    # Status and availability
    status = db.Column(db.String(50), default='available')  # available, sold, reserved
    is_active = db.Column(db.Boolean, default=True)
    
    # Tracking for automatic sold detection
    external_id = db.Column(db.String(200), nullable=True, index=True)  # Unique ID from external source (parser/API)
    last_seen_at = db.Column(db.DateTime, nullable=True)  # Last time this property was seen in import
    sold_detected_at = db.Column(db.DateTime, nullable=True)  # When property was detected as sold
    
    # Images and media
    main_image = db.Column(db.String(300), nullable=True)
    gallery_images = db.Column(db.Text, nullable=True)  # JSON array of image URLs
    
    # Technical details
    building_type = db.Column(db.String(100), nullable=True)  # монолит, кирпич, панель
    property_type = db.Column(db.String(50), nullable=True, default='Квартира')  # квартира, пентхаус, таунхаус, дом
    ceiling_height = db.Column(db.Float, nullable=True)  # Высота потолков
    
    # Coordinates for maps
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Metadata
    source_url = db.Column(db.String(300), nullable=True)  # URL источника данных
    scraped_at = db.Column(db.DateTime, nullable=True)  # Дата парсинга
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Additional parser data fields
    inner_id = db.Column(db.String(50), nullable=True)  # ID from parser
    url = db.Column(db.String(500), nullable=True)  # URL from parser
    is_apartment = db.Column(db.Boolean, default=True)
    renovation_type = db.Column(db.String(100), nullable=True)
    mortgage_price = db.Column(db.Float, nullable=True)
    min_rate = db.Column(db.Float, nullable=True)
    deal_type = db.Column(db.String(50), nullable=True)
    address = db.Column(db.String(300), nullable=True)  # Full address
    
    # Parsed address components (automatically filled from geocoding)
    # NOTE: parsed_city is kept for audit/debugging - use city_id foreign key for queries
    parsed_city = db.Column(db.String(100), nullable=True)        # Краснодар, Сочи (LEGACY - for audit only)
    parsed_district = db.Column(db.String(100), nullable=True)    # микрорайон Бытха, Центральный район (LEGACY - содержит area + settlement вместе)
    parsed_street = db.Column(db.String(300), nullable=True)      # Ясногорская улица, Красная улица
    
    # Детальная разбивка адреса (новые поля для точного поиска)
    parsed_area = db.Column(db.String(100), nullable=True)        # Административный район (Центральный р-н, Адлерский р-н)
    parsed_settlement = db.Column(db.String(100), nullable=True)  # Микрорайон/населенный пункт (мкр Бытха, мкр Донская)
    parsed_house = db.Column(db.String(50), nullable=True)        # Номер дома (280а, 16/2)
    parsed_block = db.Column(db.String(50), nullable=True)        # Корпус/литера (лит6, к2, корп 1)
    
    # Additional property details
    living_area = db.Column(db.Float, nullable=True)              # Жилая площадь
    kitchen_area = db.Column(db.Float, nullable=True)             # Площадь кухни
    building_number = db.Column(db.String(50), nullable=True)     # Корпус
    view_from_window = db.Column(db.String(200), nullable=True)   # Вид из окна
    entrance_number = db.Column(db.String(20), nullable=True)     # Подъезд
    bathroom_type = db.Column(db.String(50), nullable=True)       # Сан узел (совмещенный/раздельный)
    has_balcony = db.Column(db.Boolean, nullable=True)            # Балкон (Есть/нет)
    apartment_number = db.Column(db.String(50), nullable=True)    # Номер квартиры
    wall_material = db.Column(db.String(100), nullable=True)      # Материал стен
    
    # Relationships (Note: building relationship defined in Building model)
    developer = db.relationship('Developer', backref='properties')
    residential_complex = db.relationship('ResidentialComplex', backref='properties', foreign_keys=[complex_id])
    district = db.relationship('District', backref='properties')
    
    def __repr__(self):
        return f'<Property {self.title}>'
    
    @property
    def formatted_price(self):
        if self.price:
            if self.price >= 1000000:
                return f"{self.price / 1000000:.1f} млн ₽"
            elif self.price >= 1000:
                return f"{self.price / 1000:.0f} тыс ₽"
            return f"{self.price} ₽"
        return "Цена не указана"
    
    @property
    def room_description(self):
        if self.rooms == 0:
            return "Студия"
        elif self.rooms == 1:
            return "1-комнатная"
        elif self.rooms in [2, 3, 4]:
            return f"{self.rooms}-комнатная"
        elif self.rooms:
            return f"{self.rooms}-комн."
        return "Тип не указан"
    
    @property
    def image(self):
        """Alias for main_image for backwards compatibility"""
        return self.main_image
    
    @property
    def gallery(self):
        """Parse gallery_images JSON string into list for backwards compatibility"""
        if not self.gallery_images:
            return []
        try:
            import json
            images = json.loads(self.gallery_images)
            if isinstance(images, list):
                return images
            return []
        except:
            return []

class BookingRequest(db.Model):
    """Booking requests for properties from presentations"""
    __tablename__ = 'booking_requests'
    __table_args__ = {"extend_existing": True}
    
    # Primary key
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Property information
    property_id = db.Column(db.String(50), nullable=False)  # inner_id from excel_properties
    property_price = db.Column(db.Numeric(12, 2))
    property_address = db.Column(db.String(300))
    complex_name = db.Column(db.String(200))
    rooms_count = db.Column(db.Integer)
    area = db.Column(db.Numeric(8, 2))
    
    # Client information
    client_name = db.Column(db.String(100), nullable=False)
    client_phone = db.Column(db.String(50), nullable=False)
    client_email = db.Column(db.String(120))
    comment = db.Column(db.Text)
    
    # Request details
    presentation_id = db.Column(db.String(100))  # ID of the presentation that generated the request
    status = db.Column(db.String(20), default='new')  # new, contacted, scheduled, completed, cancelled
    
    # Manager assignment
    assigned_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Response tracking
    manager_response_time = db.Column(db.DateTime)  # When manager first responded
    client_contact_time = db.Column(db.DateTime)  # When client was actually contacted
    meeting_scheduled_time = db.Column(db.DateTime)  # If meeting was scheduled
    
    # Relationships
    assigned_manager = db.relationship('Manager', backref='booking_requests')
    
    def __repr__(self):
        return f'<BookingRequest {self.client_name} - {self.complex_name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'property_id': self.property_id,
            'property_price': float(self.property_price) if self.property_price else None,
            'property_address': self.property_address,
            'complex_name': self.complex_name,
            'rooms_count': self.rooms_count,
            'area': float(self.area) if self.area else None,
            'client_name': self.client_name,
            'client_phone': self.client_phone,
            'client_email': self.client_email,
            'comment': self.comment,
            'status': self.status,
            'presentation_id': self.presentation_id,
            'assigned_manager_id': self.assigned_manager_id,
            'assigned_manager': {
                'id': self.assigned_manager.id,
                'name': self.assigned_manager.full_name
            } if self.assigned_manager else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class UserComparison(db.Model):
    """User's comparison list for properties and complexes"""
    __tablename__ = 'user_comparisons'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), default='Мое сравнение')  # User-defined name
    is_active = db.Column(db.Boolean, default=True)  # Only one active comparison per user
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='comparisons')
    comparison_properties = db.relationship('ComparisonProperty', backref='user_comparison', cascade='all, delete-orphan')
    comparison_complexes = db.relationship('ComparisonComplex', backref='user_comparison', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<UserComparison {self.name} by User {self.user_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'is_active': self.is_active,
            'properties_count': len(self.comparison_properties),
            'complexes_count': len(self.comparison_complexes),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ManagerComparison(db.Model):
    """Manager's comparison list for properties and complexes"""
    __tablename__ = 'manager_comparisons'
    __table_args__ = {"extend_existing": True}
    
    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    name = db.Column(db.String(100), default='Сравнение для клиента')  # Manager-defined name
    client_name = db.Column(db.String(100), nullable=True)  # For whom this comparison is prepared
    is_active = db.Column(db.Boolean, default=True)  # Only one active comparison per manager
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Manager', backref='comparisons')
    comparison_properties = db.relationship('ComparisonProperty', backref='manager_comparison', cascade='all, delete-orphan')
    comparison_complexes = db.relationship('ComparisonComplex', backref='manager_comparison', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ManagerComparison {self.name} by Manager {self.manager_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'manager_id': self.manager_id,
            'name': self.name,
            'client_name': self.client_name,
            'is_active': self.is_active,
            'properties_count': len(self.comparison_properties),
            'complexes_count': len(self.comparison_complexes),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ComparisonProperty(db.Model):
    """Properties included in comparisons"""
    __tablename__ = 'comparison_properties'
    __table_args__ = (
        db.UniqueConstraint('user_comparison_id', 'property_id', name='unique_user_property_comparison'),
        db.UniqueConstraint('manager_comparison_id', 'property_id', name='unique_manager_property_comparison'),
        db.Index('idx_comparison_properties_user_comparison', 'user_comparison_id'),
        db.Index('idx_comparison_properties_manager_comparison', 'manager_comparison_id'),
        db.Index('idx_comparison_properties_property', 'property_id'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_comparison_id = db.Column(db.Integer, db.ForeignKey('user_comparisons.id'), nullable=True)
    manager_comparison_id = db.Column(db.Integer, db.ForeignKey('manager_comparisons.id'), nullable=True)
    property_id = db.Column(db.String(50), nullable=False)  # External property ID
    
    # Cached property data for fast comparison display
    property_name = db.Column(db.String(200))
    property_price = db.Column(db.BigInteger)
    complex_name = db.Column(db.String(200))
    cashback = db.Column(db.BigInteger, default=0)  # Calculated cashback amount in rubles
    area = db.Column(db.Float)
    rooms = db.Column(db.String(10))
    
    # Order in comparison (for consistent display)
    order_index = db.Column(db.Integer, default=0)
    
    # Timestamps
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ComparisonProperty {self.property_id} in comparison>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'property_id': self.property_id,
            'property_name': self.property_name,
            'property_price': self.property_price,
            'complex_name': self.complex_name,
            'cashback': self.cashback or 0,
            'area': self.area,
            'rooms': self.rooms,
            'order_index': self.order_index,
            'added_at': self.added_at.isoformat() if self.added_at else None
        }


class ComparisonComplex(db.Model):
    """Residential complexes included in comparisons"""
    __tablename__ = 'comparison_complexes'
    __table_args__ = (
        db.UniqueConstraint('user_comparison_id', 'complex_id', name='unique_user_complex_comparison'),
        db.UniqueConstraint('manager_comparison_id', 'complex_id', name='unique_manager_complex_comparison'),
        db.Index('idx_comparison_complexes_user_comparison', 'user_comparison_id'),
        db.Index('idx_comparison_complexes_manager_comparison', 'manager_comparison_id'),
        db.Index('idx_comparison_complexes_complex', 'complex_id'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_comparison_id = db.Column(db.Integer, db.ForeignKey('user_comparisons.id'), nullable=True)
    manager_comparison_id = db.Column(db.Integer, db.ForeignKey('manager_comparisons.id'), nullable=True)
    complex_id = db.Column(db.Integer, nullable=False)  # Internal complex ID
    
    # Cached complex data for fast comparison display
    complex_name = db.Column(db.String(200))
    developer_name = db.Column(db.String(200))
    min_price = db.Column(db.BigInteger)
    max_price = db.Column(db.BigInteger)
    district = db.Column(db.String(100))
    
    # ✅ ДОБАВЛЕНО: Расширенные поля ЖК для полного сравнения
    photo = db.Column(db.String(500))  # URL фото ЖК
    buildings_count = db.Column(db.Integer)  # Количество корпусов
    apartments_count = db.Column(db.Integer)  # Количество квартир
    completion_date = db.Column(db.String(100))  # Сроки сдачи
    status = db.Column(db.String(50))  # Статус: Сдан/Строится
    complex_class = db.Column(db.String(50))  # Класс: Бизнес/Комфорт/Эконом
    cashback_rate = db.Column(db.Float, default=5.0)  # Процент кэшбека ЖК из админ панели
    
    # Order in comparison (for consistent display)
    order_index = db.Column(db.Integer, default=0)
    
    # Timestamps
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ComparisonComplex {self.complex_id} in comparison>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'complex_id': self.complex_id,
            'complex_name': self.complex_name,
            'developer_name': self.developer_name,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'district': self.district,
            'photo': self.photo,
            'buildings_count': self.buildings_count,
            'apartments_count': self.apartments_count,
            'completion_date': self.completion_date,
            'status': self.status,
            'complex_class': self.complex_class,
            'cashback_rate': self.cashback_rate or 5.0,
            'order_index': self.order_index,
            'added_at': self.added_at.isoformat() if self.added_at else None
        }


class UserActivity(db.Model):
    """User activity tracking model for dashboard recent activity"""
    __tablename__ = 'user_activities'
    __table_args__ = (
        db.Index('idx_user_activities_user_id', 'user_id'),
        db.Index('idx_user_activities_created_at', 'created_at'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'favorite_added', 'comparison_added', 'search_saved', 'property_viewed', 'complex_viewed'
    description = db.Column(db.String(200), nullable=False)  # Human-readable description
    
    # Optional related object IDs
    property_id = db.Column(db.String(20), nullable=True)  # For property-related activities
    complex_id = db.Column(db.Integer, nullable=True)  # For complex-related activities
    search_query = db.Column(db.String(200), nullable=True)  # For search-related activities
    
    # Additional data
    extra_data = db.Column(db.Text, nullable=True)  # JSON string for additional data
    ip_address = db.Column(db.String(45), nullable=True)  # User IP for security
    user_agent = db.Column(db.String(500), nullable=True)  # Browser info
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('activities', lazy='dynamic', order_by='UserActivity.created_at.desc()'))
    
    def __repr__(self):
        return f'<UserActivity {self.activity_type} by user {self.user_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'activity_type': self.activity_type,
            'description': self.description,
            'property_id': self.property_id,
            'complex_id': self.complex_id,
            'search_query': self.search_query,
            'extra_data': json.loads(self.extra_data) if self.extra_data else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @staticmethod
    def log_activity(user_id, activity_type, description, **kwargs):
        """Helper method to log user activity"""
        activity = UserActivity(
            user_id=user_id,
            activity_type=activity_type,
            description=description,
            property_id=kwargs.get('property_id'),
            complex_id=kwargs.get('complex_id'),
            search_query=kwargs.get('search_query'),
            extra_data=json.dumps(kwargs.get('extra_data', {})) if kwargs.get('extra_data') else None,
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent')
        )
        db.session.add(activity)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error logging activity: {e}")
    
    @staticmethod
    def get_recent_activities(user_id, limit=10):
        """Get recent activities for a user"""
        return UserActivity.query.filter_by(user_id=user_id).order_by(UserActivity.created_at.desc()).limit(limit).all()


class EmailVerificationAttempt(db.Model):
    """Track email verification resend attempts for rate limiting"""
    __tablename__ = 'email_verification_attempts'
    __table_args__ = (
        db.Index('idx_verification_attempts_email', 'email'),
        db.Index('idx_verification_attempts_created_at', 'created_at'),
        {"extend_existing": True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    success = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @classmethod
    def can_resend_verification(cls, email, rate_limit_minutes=5):
        """Check if user can resend verification email based on rate limiting"""
        from datetime import timedelta
        
        # Check last successful attempt
        time_threshold = datetime.utcnow() - timedelta(minutes=rate_limit_minutes)
        recent_attempt = cls.query.filter(
            cls.email == email,
            cls.success == True,
            cls.created_at > time_threshold
        ).first()
        
        return recent_attempt is None
    
    @classmethod
    def get_recent_attempts_count(cls, email, hours=1):
        """Get count of recent attempts for security monitoring"""
        from datetime import timedelta
        
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        return cls.query.filter(
            cls.email == email,
            cls.created_at > time_threshold
        ).count()
    
    @classmethod
    def log_attempt(cls, email, ip_address=None, user_agent=None, success=False, error_message=None):
        """Log a verification resend attempt"""
        attempt = cls(
            email=email,
            ip_address=ip_address,
            user_agent=user_agent, 
            success=success,
            error_message=error_message
        )
        
        try:
            from app import db
            db.session.add(attempt)
            db.session.commit()
            return attempt
        except Exception as e:
            db.session.rollback()
            print(f"Error logging verification attempt: {e}")
            return None
    
    def __repr__(self):
        return f'<EmailVerificationAttempt {self.email} at {self.created_at}>'


class JobCategory(db.Model):
    """Job category model for organizing vacancies"""
    __tablename__ = 'job_categories'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(50), nullable=True)  # FontAwesome icon class
    color = db.Column(db.String(20), default='blue', nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    jobs = db.relationship('Job', backref='category', lazy='dynamic')
    
    def __repr__(self):
        return f'<JobCategory {self.name}>'
    
    @property
    def jobs_count(self):
        """Count of active jobs in this category (excluding paused jobs)"""
        return self.jobs.filter(Job.is_active == True, Job.status == 'active').count()


class Job(db.Model):
    """Job/Vacancy model"""
    __tablename__ = 'jobs'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('job_categories.id'), nullable=False)
    
    # Job details
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=True)
    benefits = db.Column(db.Text, nullable=True)
    responsibilities = db.Column(db.Text, nullable=True)
    
    # Employment details
    employment_type = db.Column(db.String(50), default='full_time', nullable=False)  # full_time, part_time, contract
    location = db.Column(db.String(200), nullable=False)  # Краснодар / Удаленно
    is_remote = db.Column(db.Boolean, default=False)
    experience_level = db.Column(db.String(50), nullable=True)  # Опыт: "Опыт от 1 года", "Опыт от 3 лет", "Опыт от 5 лет", "Без опыта" или junior, middle, senior для совместимости
    
    # Salary information
    salary_min = db.Column(db.Integer, nullable=True)
    salary_max = db.Column(db.Integer, nullable=True)
    salary_currency = db.Column(db.String(10), default='RUB', nullable=False)
    salary_period = db.Column(db.String(20), default='month', nullable=False)  # month, year, hour
    
    # Skills and tags
    skills = db.Column(db.Text, nullable=True)  # JSON array of skills
    tags = db.Column(db.Text, nullable=True)  # JSON array of tags for filtering
    
    # Status and visibility
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    is_urgent = db.Column(db.Boolean, default=False, nullable=False)  # Urgent job posting
    status = db.Column(db.String(50), default='active', nullable=False)  # active, paused, closed
    priority = db.Column(db.Integer, default=0)  # Higher priority jobs appear first
    
    # Company information
    department = db.Column(db.String(100), nullable=True)  # Department/division
    
    # SEO
    meta_title = db.Column(db.String(200), nullable=True)
    meta_description = db.Column(db.Text, nullable=True)
    
    # Contact information
    contact_email = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    
    # Tracking
    views_count = db.Column(db.Integer, default=0)
    applications_count = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    applications = db.relationship('JobApplication', backref='job', lazy='dynamic')
    
    def __repr__(self):
        return f'<Job {self.title}>'
    
    @property
    def salary_range(self):
        """Format salary range for display"""
        if self.salary_min and self.salary_max:
            return f"от {self.salary_min:,} до {self.salary_max:,} ₽"
        elif self.salary_min:
            return f"от {self.salary_min:,} ₽"
        elif self.salary_max:
            return f"до {self.salary_max:,} ₽"
        return "Зарплата по договоренности"
    
    @property
    def skills_list(self):
        """Get skills as list"""
        if self.skills:
            try:
                return json.loads(self.skills)
            except:
                return []
        return []
    
    @property
    def tags_list(self):
        """Get tags as list"""
        if self.tags:
            try:
                return json.loads(self.tags)
            except:
                return []
        return []
    
    def is_expired(self):
        """Check if job posting has expired"""
        if self.expires_at:
            return datetime.utcnow() > self.expires_at
        return False


class JobApplication(db.Model):
    """Job application model to track applications"""
    __tablename__ = 'job_applications'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    
    # Applicant information
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    
    # Application details
    cover_letter = db.Column(db.Text, nullable=True)
    resume_filename = db.Column(db.String(255), nullable=True)
    resume_path = db.Column(db.String(500), nullable=True)
    
    # Status tracking
    status = db.Column(db.String(50), default='new', nullable=False)  # new, reviewed, interview, hired, rejected
    notes = db.Column(db.Text, nullable=True)  # Internal notes from HR
    
    # Tracking
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<JobApplication {self.first_name} {self.last_name} for {self.job.title}>'
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Deal(db.Model):
    """Deal model for transactions between managers and clients"""
    __tablename__ = 'deals'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    deal_number = db.Column(db.String(20), unique=True, nullable=False)  # Номер сделки (DL12345678)
    
    # Relations
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    residential_complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=True)
    residential_complex_name = db.Column(db.String(255), nullable=True)  # Текстовое название ЖК
    
    # Deal details
    property_price = db.Column(db.Numeric(15, 2), nullable=False)  # Стоимость объекта
    cashback_amount = db.Column(db.Numeric(15, 2), nullable=False)  # Сумма кешбека
    
    # Property details
    property_description = db.Column(db.Text, nullable=True)  # Описание объекта
    property_floor = db.Column(db.Integer, nullable=True)  # Этаж
    property_area = db.Column(db.Float, nullable=True)  # Площадь
    property_rooms = db.Column(db.String(10), nullable=True)  # Количество комнат
    
    # Status and progress
    status = db.Column(db.String(50), default='new', nullable=False)  # new, reserved, mortgage, completed, rejected
    notes = db.Column(db.Text, nullable=True)  # Заметки менеджера
    client_notes = db.Column(db.Text, nullable=True)  # Заметки клиента
    
    # Lead source
    source = db.Column(db.String(100), nullable=True)  # Источник: Форма обратного звонка, Заявка на подбор, Бронирование, Кешбек, Менеджер
    
    # Closing details
    rejection_reason = db.Column(db.String(100), nullable=True)  # Причина проигрыша
    closing_comment = db.Column(db.Text, nullable=True)  # Комментарий при закрытии
    closed_at = db.Column(db.DateTime, nullable=True)  # Дата закрытия
    
    # Contract details
    contract_date = db.Column(db.Date, nullable=True)  # Дата договора
    completion_date = db.Column(db.Date, nullable=True)  # Дата завершения
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Manager', backref='deals')
    client = db.relationship('User', backref='deals')
    residential_complex = db.relationship('ResidentialComplex', backref='deals')
    
    def __init__(self, **kwargs):
        super(Deal, self).__init__(**kwargs)
        if not self.deal_number:
            self.deal_number = self.generate_deal_number()
    
    def generate_deal_number(self):
        """Generate unique deal number in format DL12345678"""
        import random
        while True:
            deal_number = f"DL{random.randint(10000000, 99999999)}"
            if not Deal.query.filter_by(deal_number=deal_number).first():
                return deal_number

    STAGE_ORDER = [
        'new', 'in_progress', 'calculation', 'meeting_scheduled', 'meeting_done',
        'postponed', 'verbal_reserve', 'reserved', 'documents', 'mortgage',
        'ddu_preparation', 'ddu_signing', 'registration', 'receivables', 'completed', 'rejected'
    ]

    STAGE_LABELS = {
        'new': 'Новая',
        'in_progress': 'В работе',
        'calculation': 'Сделан расчёт',
        'meeting_scheduled': 'Встреча назначена',
        'meeting_done': 'Встреча проведена',
        'postponed': 'Отложена',
        'verbal_reserve': 'Устная бронь',
        'reserved': 'Бронь',
        'documents': 'Сбор документов',
        'mortgage': 'Ипотека',
        'ddu_preparation': 'Подготовка ДДУ',
        'ddu_signing': 'Подписание ДДУ',
        'registration': 'Регистрация',
        'receivables': 'Дебиторка',
        'completed': 'Завершена',
        'rejected': 'Отклонена',
        'object_reserved': 'Забронирован',
        'successful': 'Завершена',
    }

    STAGE_COLORS = {
        'new': '#3b82f6',
        'in_progress': '#0088CC',
        'calculation': '#6366f1',
        'meeting_scheduled': '#8b5cf6',
        'meeting_done': '#a855f7',
        'postponed': '#f59e0b',
        'verbal_reserve': '#f97316',
        'reserved': '#ef4444',
        'documents': '#ec4899',
        'mortgage': '#14b8a6',
        'ddu_preparation': '#06b6d4',
        'ddu_signing': '#0284c7',
        'registration': '#4f46e5',
        'receivables': '#dc2626',
        'completed': '#059669',
        'rejected': '#6b7280',
        'object_reserved': '#f59e0b',
        'successful': '#059669',
    }

    @property
    def status_display(self):
        return self.STAGE_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STAGE_COLORS.get(self.status, '#6b7280')

    @property
    def stage_index(self):
        if self.status in self.STAGE_ORDER:
            return self.STAGE_ORDER.index(self.status)
        return -1

    def get_cashback_percentage(self):
        if self.property_price and self.cashback_amount:
            return float(self.cashback_amount) / float(self.property_price) * 100
        return 0

    @property
    def is_locked(self):
        stages = DealStageConfig.get_ordered_stages()
        if stages:
            stage_cfg = next((s for s in stages if s.key == self.status), None)
            if stage_cfg:
                return stage_cfg.is_terminal
        return self.status in ['completed', 'successful', 'rejected']

    def can_edit(self, user_id, is_manager=False):
        if self.is_locked:
            return False
        if is_manager:
            return self.manager_id == user_id
        return self.client_id == user_id

    @staticmethod
    def get_stages_config():
        stages = DealStageConfig.get_ordered_stages()
        if stages:
            return {
                'order': [s.key for s in stages],
                'labels': {s.key: s.label for s in stages},
                'colors': {s.key: s.color for s in stages},
            }
        return {
            'order': Deal.STAGE_ORDER,
            'labels': Deal.STAGE_LABELS,
            'colors': Deal.STAGE_COLORS,
        }

    def __repr__(self):
        return f'<Deal {self.deal_number} - {self.status}>'


class DealComment(db.Model):
    __tablename__ = 'deal_comments'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deal = db.relationship('Deal', backref=db.backref('comments', lazy='dynamic', order_by='DealComment.created_at.desc()'))
    author = db.relationship('Manager', backref='deal_comments')


class DealTask(db.Model):
    __tablename__ = 'deal_tasks'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    priority = db.Column(db.String(20), default='normal')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deal = db.relationship('Deal', backref=db.backref('tasks', lazy='dynamic', order_by='DealTask.created_at.desc()'))
    author = db.relationship('Manager', backref='deal_tasks')

    PRIORITY_LABELS = {'low': 'Низкий', 'normal': 'Обычный', 'high': 'Высокий', 'urgent': 'Срочный'}

    @property
    def priority_label(self):
        return self.PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def is_overdue(self):
        if self.due_date and not self.is_completed:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo
            moscow_now = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
            return moscow_now > self.due_date
        return False


class DealHistory(db.Model):
    __tablename__ = 'deal_history'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    field_name = db.Column(db.String(100), nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    deal = db.relationship('Deal', backref=db.backref('history', lazy='dynamic', order_by='DealHistory.created_at.desc()'))
    author = db.relationship('Manager', backref='deal_history_entries')

    ACTION_LABELS = {
        'stage_change': 'Изменение этапа',
        'field_change': 'Изменение поля',
        'field_update': 'Обновление поля',
        'comment_added': 'Добавлен комментарий',
        'task_created': 'Создана задача',
        'task_completed': 'Задача выполнена',
        'deal_created': 'Сделка создана',
        'responsible_change': 'Смена ответственного',
        'status_change': 'Изменение статуса',
    }


class DealStageConfig(db.Model):
    __tablename__ = 'deal_stage_configs'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(20), default='#6b7280', nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_terminal = db.Column(db.Boolean, default=False, nullable=False)
    is_success = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def get_ordered_stages():
        stages = DealStageConfig.query.filter_by(is_active=True).order_by(DealStageConfig.sort_order).all()
        if not stages:
            return None
        return stages

    @staticmethod
    def seed_defaults():
        if DealStageConfig.query.first():
            return
        defaults = [
            ('new', 'Новая', '#3b82f6', 0, False, False),
            ('in_progress', 'В работе', '#0088CC', 1, False, False),
            ('calculation', 'Сделан расчёт', '#0ea5e9', 2, False, False),
            ('meeting_scheduled', 'Встреча назначена', '#06b6d4', 3, False, False),
            ('meeting_done', 'Встреча проведена', '#14b8a6', 4, False, False),
            ('postponed', 'Отложена', '#f59e0b', 5, False, False),
            ('verbal_reserve', 'Устная бронь', '#f97316', 6, False, False),
            ('reserved', 'Бронь', '#ef4444', 7, False, False),
            ('documents', 'Сбор документов', '#ec4899', 8, False, False),
            ('mortgage', 'Ипотека', '#14b8a6', 9, False, False),
            ('ddu_preparation', 'Подготовка ДДУ', '#06b6d4', 10, False, False),
            ('ddu_signing', 'Подписание ДДУ', '#0284c7', 11, False, False),
            ('registration', 'Регистрация', '#0088CC', 12, False, False),
            ('receivables', 'Дебиторка', '#dc2626', 13, False, False),
            ('completed', 'Завершена', '#059669', 14, True, True),
            ('rejected', 'Отклонена', '#6b7280', 15, True, False),
        ]
        for key, label, color, order, is_terminal, is_success in defaults:
            db.session.add(DealStageConfig(
                key=key, label=label, color=color, sort_order=order,
                is_terminal=is_terminal, is_success=is_success
            ))
        db.session.commit()


class Offer(db.Model):
    """Promotional offers/special deals for residential complexes"""
    __tablename__ = 'offers'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    residential_complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=False)
    
    # Offer content
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=False)
    
    # Status and ordering
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    residential_complex = db.relationship('ResidentialComplex', backref='offers')
    
    def __repr__(self):
        return f'<Offer {self.title} for Complex #{self.residential_complex_id}>'


class MarketingMaterial(db.Model):
    """Marketing materials for residential complexes (brochures, photos, renders, etc.)"""
    __tablename__ = 'marketing_materials'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    residential_complex_id = db.Column(db.Integer, db.ForeignKey('residential_complexes.id'), nullable=False)
    
    # Material content
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(500), nullable=False)
    
    # Material classification
    file_type = db.Column(db.String(20), nullable=False)  # 'pdf', 'image'
    material_type = db.Column(db.String(50), nullable=False)  # 'brochure', 'photo', 'render', 'other'
    
    # Status and ordering
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    residential_complex = db.relationship('ResidentialComplex', backref='marketing_materials')
    
    def __repr__(self):
        return f'<MarketingMaterial {self.title} ({self.material_type}) for Complex #{self.residential_complex_id}>'


class UserBalance(db.Model):
    """Detailed balance tracking for each user"""
    __tablename__ = 'user_balances'
    __table_args__ = (
        db.UniqueConstraint('user_id', name='unique_user_balance'),
        db.Index('idx_user_balance_user', 'user_id'),
        {'extend_existing': True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Balance details
    available_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Доступно для вывода
    pending_amount = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # В обработке (заявки на вывод)
    total_earned = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Всего заработано
    total_withdrawn = db.Column(db.Numeric(15, 2), default=Decimal('0.00'), nullable=False)  # Всего выведено
    
    # Currency
    currency = db.Column(db.String(3), default='RUB', nullable=False)  # RUB, USD, EUR
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_transaction_at = db.Column(db.DateTime, nullable=True)  # Последняя транзакция
    
    # Relationship
    user = db.relationship('User', backref=db.backref('user_balance', uselist=False))  # One-to-one
    
    def __repr__(self):
        return f'<UserBalance User #{self.user_id}: {self.available_amount}₽ available, {self.pending_amount}₽ pending>'
    
    @property
    def total_balance(self):
        """Total balance including pending"""
        return self.available_amount + self.pending_amount


class BalanceTransaction(db.Model):
    """Balance transaction history for users"""
    __tablename__ = 'balance_transactions'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Transaction details
    amount = db.Column(db.Numeric(15, 2), nullable=False)  # Сумма (может быть + или -)
    transaction_type = db.Column(db.String(50), nullable=False)  # registration_bonus, cashback_earned, withdrawal, refund, bonus, adjustment
    description = db.Column(db.String(500), nullable=False)  # Описание транзакции
    
    # Balance snapshot
    balance_before = db.Column(db.Numeric(15, 2), nullable=False)  # Баланс до транзакции
    balance_after = db.Column(db.Numeric(15, 2), nullable=False)  # Баланс после транзакции
    
    # Related objects
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), nullable=True)  # Связь со сделкой (если это кешбек)
    cashback_application_id = db.Column(db.Integer, db.ForeignKey('cashback_applications.id'), nullable=True)  # Связь с заявкой
    withdrawal_request_id = db.Column(db.Integer, db.ForeignKey('withdrawal_requests.id'), nullable=True)  # Связь с заявкой на вывод
    
    # Audit - кто создал транзакцию
    created_by_id = db.Column(db.Integer, db.ForeignKey('admins.id'), nullable=True)  # Админ, создавший транзакцию (если вручную)
    
    # Metadata
    status = db.Column(db.String(50), default='completed', nullable=False)  # completed, pending, failed, cancelled
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)  # Когда обработана
    
    # Relationships
    user = db.relationship('User', backref='balance_transactions')
    deal = db.relationship('Deal', backref='balance_transactions')
    cashback_application = db.relationship('CashbackApplication', backref='balance_transactions')
    withdrawal_request = db.relationship('WithdrawalRequest', backref='balance_transactions', foreign_keys=[withdrawal_request_id])
    created_by = db.relationship('Admin', backref='created_transactions', foreign_keys=[created_by_id])
    
    def __repr__(self):
        return f'<BalanceTransaction {self.transaction_type} {self.amount}₽ for User #{self.user_id}>'


class WithdrawalRequest(db.Model):
    """User requests to withdraw funds from their balance"""
    __tablename__ = 'withdrawal_requests'
    __table_args__ = (
        db.Index('idx_withdrawal_user_status', 'user_id', 'status'),
        db.Index('idx_withdrawal_status', 'status'),
        {'extend_existing': True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # Withdrawal details
    amount = db.Column(db.Numeric(15, 2), nullable=False)  # Сумма к выводу
    payout_method = db.Column(db.String(50), nullable=False)  # bank_card, bank_account, yoomoney, qiwi
    payout_details = db.Column(db.Text, nullable=False)  # JSON с реквизитами (номер карты, счёт и т.д.)
    
    # Status workflow: pending → approved → paid OR pending → rejected
    status = db.Column(db.String(50), default='pending', nullable=False, index=True)  # pending, approved, paid, rejected
    
    # Processing info
    processed_by_id = db.Column(db.Integer, db.ForeignKey('admins.id'), nullable=True)  # Админ, обработавший заявку
    rejection_reason = db.Column(db.String(500), nullable=True)  # Причина отклонения
    admin_notes = db.Column(db.Text, nullable=True)  # Заметки админа
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)  # Когда обработана (одобрена/отклонена)
    paid_at = db.Column(db.DateTime, nullable=True)  # Когда выплачена
    
    # Relationships
    user = db.relationship('User', backref='withdrawal_requests')
    processed_by = db.relationship('Admin', backref='processed_withdrawals', foreign_keys=[processed_by_id])
    
    def __repr__(self):
        return f'<WithdrawalRequest #{self.id} {self.amount}₽ {self.status} for User #{self.user_id}>'
    
    @property
    def payout_details_dict(self):
        """Parse JSON payout_details to dict"""
        try:
            return json.loads(self.payout_details) if self.payout_details else {}
        except:
            return {}
    
    @payout_details_dict.setter
    def payout_details_dict(self, value):
        """Store dict as JSON in payout_details"""
        self.payout_details = json.dumps(value, ensure_ascii=False) if value else '{}'


class ManagerCheckin(db.Model):
    __tablename__ = 'manager_checkins'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=False)
    check_in_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    check_out_time = db.Column(db.DateTime, nullable=True)
    date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    manager = db.relationship('Manager', backref=db.backref('checkins', lazy='dynamic'))

    @property
    def duration_minutes(self):
        if self.check_out_time and self.check_in_time:
            return int((self.check_out_time - self.check_in_time).total_seconds() / 60)
        elif self.is_active and self.check_in_time:
            from zoneinfo import ZoneInfo
            now_moscow = datetime.now(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)
            return int((now_moscow - self.check_in_time).total_seconds() / 60)
        return 0

    @property
    def duration_display(self):
        mins = self.duration_minutes
        hours = mins // 60
        remaining = mins % 60
        if hours > 0:
            return f'{hours}ч {remaining}м'
        return f'{remaining}м'


class Department(db.Model):
    __tablename__ = 'departments'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    head_manager_id = db.Column(db.Integer, db.ForeignKey('managers.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship('Department', remote_side=[id], backref=db.backref('children', lazy='dynamic'))
    head_manager = db.relationship('Manager', foreign_keys=[head_manager_id], backref='headed_department')
    members = db.relationship('Manager', foreign_keys='Manager.department_id', backref='department', lazy='dynamic')

    @property
    def full_path(self):
        parts = [self.name]
        current = self.parent
        while current:
            parts.insert(0, current.name)
            current = current.parent
        return ' → '.join(parts)

    @property
    def member_count(self):
        return self.members.filter_by(is_active=True).count()

    def get_all_subordinate_ids(self):
        ids = [self.id]
        for child in self.children.filter_by(is_active=True).all():
            ids.extend(child.get_all_subordinate_ids())
        return ids

    def get_all_manager_ids(self):
        dept_ids = self.get_all_subordinate_ids()
        from sqlalchemy import text
        managers = Manager.query.filter(Manager.department_id.in_(dept_ids), Manager.is_active == True).all()
        return [m.id for m in managers]


class OrgRole(db.Model):
    __tablename__ = 'org_roles'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    level = db.Column(db.Integer, default=0)
    is_system = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    can_view_all_deals = db.Column(db.Boolean, default=False)
    can_view_department_deals = db.Column(db.Boolean, default=False)
    can_view_own_deals = db.Column(db.Boolean, default=True)
    can_change_deal_responsible = db.Column(db.Boolean, default=False)
    can_view_all_archive = db.Column(db.Boolean, default=False)
    can_view_department_archive = db.Column(db.Boolean, default=False)
    can_view_own_archive = db.Column(db.Boolean, default=True)
    can_manage_department = db.Column(db.Boolean, default=False)
    can_view_statistics = db.Column(db.Boolean, default=False)
    can_manage_managers = db.Column(db.Boolean, default=False)
    can_receive_leads = db.Column(db.Boolean, default=False)

    members = db.relationship('Manager', backref='org_role', lazy='dynamic')

    @staticmethod
    def seed_defaults():
        if OrgRole.query.first():
            return
        defaults = [
            {
                'name': 'Директор', 'key': 'director', 'level': 100, 'is_system': True,
                'can_view_all_deals': True, 'can_view_department_deals': True, 'can_view_own_deals': True,
                'can_change_deal_responsible': True, 'can_view_all_archive': True,
                'can_view_department_archive': True, 'can_view_own_archive': True,
                'can_manage_department': True, 'can_view_statistics': True, 'can_manage_managers': True,
            },
            {
                'name': 'РОП', 'key': 'rop', 'level': 50, 'is_system': True,
                'can_view_all_deals': False, 'can_view_department_deals': True, 'can_view_own_deals': True,
                'can_change_deal_responsible': True, 'can_view_all_archive': False,
                'can_view_department_archive': True, 'can_view_own_archive': True,
                'can_manage_department': True, 'can_view_statistics': True, 'can_manage_managers': False,
            },
            {
                'name': 'Менеджер', 'key': 'manager', 'level': 10, 'is_system': True,
                'can_view_all_deals': False, 'can_view_department_deals': False, 'can_view_own_deals': True,
                'can_change_deal_responsible': False, 'can_view_all_archive': False,
                'can_view_department_archive': False, 'can_view_own_archive': True,
                'can_manage_department': False, 'can_view_statistics': False, 'can_manage_managers': False,
            },
        ]
        for d in defaults:
            db.session.add(OrgRole(**d))
        db.session.commit()

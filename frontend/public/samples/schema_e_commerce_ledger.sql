-- Lược đồ Cơ sở Dữ liệu Sổ cái Giao dịch & Thanh toán Đa đối tượng (Nhóm C1SE.27)
CREATE TABLE tenants (
    tenant_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Bảng tài khoản người dùng gắn liền với từng Tenant
CREATE TABLE user_accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'USER',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sổ cái giao dịch thanh toán đảm bảo tính Bất biến (Idempotent) và Khóa lạc quan (Version)
CREATE TABLE payment_transactions (
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    account_id UUID REFERENCES user_accounts(account_id),
    idempotency_key VARCHAR(128) UNIQUE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    payment_method VARCHAR(64) NOT NULL,
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_transactions_tenant_status ON payment_transactions(tenant_id, status);
CREATE INDEX idx_transactions_idempotency ON payment_transactions(idempotency_key);

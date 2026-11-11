# Kiến Trúc An Toàn Thông Tin & Phân Quyền Hệ Thống (Nhóm C1SE.27)

## Kiến Trúc Xác Thực (Authentication)
1. **Ký Số Token JWT Bất Đối Xứng Chuẩn RS256**:
   - Access Token có thời gian sống (TTL) tối đa 15 phút.
   - Refresh Token được lưu trữ bảo mật trong HTTP-Only, Secure, SameSite=Strict cookies.
   - Mỗi payload token bắt buộc phải chứa `sub`, `tenant_id`, và các vai trò `roles`.

## Giao Thức Xác Thực Chữ Ký Webhook
Mọi webhook từ đối tác bên ngoài gửi đến đều phải có tiêu đề `Stripe-Signature`:
```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## Ma Trận Kiểm Soát Truy Cập Dựa Trên Vai Trò (RBAC Matrix)
- `SUPER_ADMIN`: Toàn quyền đồng bộ CSDL, khởi tạo Tenant, và luân chuyển khóa bí mật (Key Rotation).
- `TENANT_OPERATOR`: Quản lý sổ cái giao dịch và xử lý khiếu nại hoàn tiền.
- `END_USER`: Chỉ có quyền tạo yêu cầu thanh toán trên chính `account_id` của mình.

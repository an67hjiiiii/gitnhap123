# Cấp quyền ADMIN cho một tài khoản đã đăng ký (để thấy trang "Cơ sở dữ liệu").
# Dùng: powershell -ExecutionPolicy Bypass -File scripts/dev/make-admin.ps1 ten@email.com   (thêm -Revoke để hạ về USER)
param([Parameter(Mandatory = $true)][string]$Email, [switch]$Revoke)
$ErrorActionPreference = 'Continue'  # lỗi thật được bắt qua $LASTEXITCODE và throw
. "$PSScriptRoot/_common.ps1"
Start-DockerEngine
if ($Email -notmatch '^[^@\s'']+@[^@\s'']+$') { throw 'Email không hợp lệ.' }
$role = if ($Revoke) { 'USER' } else { 'ADMIN' }
$sql = "UPDATE users SET role='$role', updated_at=now() WHERE lower(email)=lower('$Email');"
$out = docker exec cap1-ai-midterm-postgres psql -U cap1_ai -d cap1_ai_midterm_multilingual -tAc $sql
if ($LASTEXITCODE -ne 0) { throw 'Không chạy được lệnh trên PostgreSQL (Docker đã bật chưa?).' }
if ($out -match 'UPDATE 0') { throw "Không có tài khoản $Email. Hãy đăng ký trên trang web trước." }
Write-Host "Đã đặt $Email thành $role. Đăng xuất rồi đăng nhập lại để thấy thay đổi."

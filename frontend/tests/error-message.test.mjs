import test from 'node:test';
import assert from 'node:assert/strict';
import { contextOfPath, friendlyMessage } from '../src/lib/errorMessage.ts';

const cases = [
  ['401 login', { status: 401, context: 'login' }, 'Email hoặc mật khẩu chưa đúng. Bạn kiểm tra lại nhé.'],
  ['401 session', { status: 401 }, 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'],
  ['403', { status: 403 }, 'Bạn chưa có quyền thực hiện thao tác này.'],
  ['404', { status: 404 }, 'Không tìm thấy nội dung được yêu cầu. Có thể nó đã bị xoá.'],
  ['409', { status: 409 }, 'Nội dung này đã tồn tại hoặc đang được xử lý. Hãy làm mới trang rồi thử lại.'],
  ['422', { status: 422 }, 'Thông tin chưa hợp lệ. Bạn kiểm tra lại các ô đã nhập.'],
  ['422 upload', { status: 422, context: 'upload' }, 'Tệp chưa hợp lệ. Dùng PDF, Markdown, TXT hoặc SQL, tối đa 2 MB.'],
  ['429', { status: 429 }, 'Bạn thao tác hơi nhanh. Vui lòng đợi một lát rồi thử lại.'],
  ['500', { status: 500 }, 'Máy chủ gặp lỗi. Vui lòng thử lại sau ít phút.'],
  ['502', { status: 502 }, 'Máy chủ đang bận hoặc đang khởi động. Vui lòng thử lại sau ít phút.'],
  ['503', { status: 503 }, 'Máy chủ đang bận hoặc đang khởi động. Vui lòng thử lại sau ít phút.'],
  ['network', { network: true }, 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.'],
  ['timeout', { timeout: true }, 'Máy chủ phản hồi quá lâu. Vui lòng thử lại.'],
  ['unknown', { status: 418 }, 'Có lỗi xảy ra. Vui lòng thử lại.'],
];

for (const [name, input, expected] of cases) {
  test(name, () => {
    const message = friendlyMessage(input);
    assert.equal(message, expected);
    assert.doesNotMatch(message, /HTTP/i);
  });
}

test('Vietnamese detail wins', () => assert.equal(friendlyMessage({ status: 500, detail: 'Lỗi máy chủ' }), 'Lỗi máy chủ'));
test('English detail is not echoed', () => assert.notEqual(friendlyMessage({ status: 401, detail: 'Invalid email, username, or password', context: 'login' }), 'Invalid email, username, or password'));

test('contextOfPath maps endpoint paths', () => {
  assert.equal(contextOfPath('/auth/login'), 'login');
  assert.equal(contextOfPath('/auth/register'), 'login');
  assert.equal(contextOfPath('/sources'), 'upload');
  assert.equal(contextOfPath('/sources/file'), 'upload');
  assert.equal(contextOfPath('/chat'), 'chat');
  assert.equal(contextOfPath('/auth/session'), 'session');
  assert.equal(contextOfPath('/health'), 'general');
});

## Why

系统目前没有用户身份认证能力，任何调用方都无法验证身份。需要提供用户名密码登录接口，作为后续受保护资源访问控制的基础。

## What Changes

- 新增用户登录 API（`POST /auth/login`），接受用户名和密码，校验成功后返回访问令牌。
- 密码以安全哈希形式存储与校验（bcrypt），不存明文。
- 校验失败返回明确的错误响应（401），不泄露账户是否存在。
- 新增 `user-auth` 能力规范，定义登录接口的外部可观察行为。

## Capabilities

### New Capabilities

- `user-auth`: 用户名密码登录能力，定义登录接口的请求/响应、错误语义与令牌返回行为。

### Modified Capabilities

<!-- 无既有能力被修改 -->

## Impact

- 新增后端模块：认证路由、密码哈希工具、用户数据访问（FastAPI + Python）。
- 新增依赖：`bcrypt`（或 `passlib[bcrypt]`）用于密码哈希。
- 新增 API 端点 `POST /auth/login`。
- 无前端界面改动（本次仅后端 API）。

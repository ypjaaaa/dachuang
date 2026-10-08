## 1. 项目与依赖搭建

- [x] 1.1 初始化 FastAPI 项目结构与虚拟环境，验证 `uvicorn` 可启动一个空应用并响应 `/` 健康检查
- [x] 1.2 添加依赖（`fastapi`、`uvicorn`、`sqlalchemy`、`passlib[bcrypt]`、`PyJWT`、`pydantic`）到 `requirements.txt` 或 `pyproject.toml`，验证 `pip install` 成功

## 2. 用户存储

- [x] 2.1 定义 `users` 表模型（`username` 唯一、`password_hash`），验证 `sqlalchemy` 建表成功
- [x] 2.2 实现 `UserRepository.get_by_username(username)`，验证针对已存在与不存在的用户名分别返回用户对象与 `None`

## 3. 密码哈希

- [x] 3.1 实现密码哈希工具（bcrypt `CryptContext`，`hash` / `verify`），验证相同密码校验通过、错误密码校验失败、且存储中不含明文密码

## 4. 访问令牌签发

- [x] 4.1 实现 JWT 签发函数（HS256，含 `sub` 与 `exp`），验证生成的令牌可被解码并包含正确的 `sub` 与 `exp`

## 5. 登录端点

- [x] 5.1 实现 `POST /auth/login` 端点，凭据正确时返回 200 与 `access_token` 及过期时间，验证请求体校验、正确/错误凭据、用户不存在三类场景的响应符合 spec

## 6. 账户枚举防护与测试

- [x] 6.1 对不存在的用户也执行一次 dummy bcrypt 校验以拉平耗时，验证不存在用户与错误密码的响应时间接近
- [x] 6.2 编写并运行测试（覆盖 spec 中全部场景），验证所有测试通过且登录端点行为满足 `user-auth` 规范

# 本地验证

```powershell
python -m unittest -v
node tests/dashboard.test.cjs
```

Python 检查采集结构、32 条语言对照案例、来源身份归属、模型输出验证、上下文复审、失败回退、去重和 HTML 转义。模型传输测试只使用本地模拟服务器，不需要 API Key。

Node 检查多标签计数、占比分母、筛选与累计数据更新。没有依赖第三方图表库。

演示数据由这些合成案例组成，不对应任何真实账号。测试通过不是对真实世界识别准确率的声明。

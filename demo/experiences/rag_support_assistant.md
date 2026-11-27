# 智能客服 RAG 问答助手

## 基本信息
- 项目类型：个人项目（虚构演示数据）。
- 时间：2025-09 至 2025-12。
- 团队规模：1 人。
- 技术栈：Python、FastAPI、LangChain、PostgreSQL、pgvector、React、Docker。

## 我的工作 检索增强问答链路
我为一个示例电商客服场景搭建了 RAG 问答链路：把 320 篇帮助中心文章按标题切分成片段，用开源中文向量模型编码后存入 PostgreSQL 的 pgvector，回答时先检索最相关的 5 个片段，再交给大模型生成带引用的回答。我用 LangChain 封装了模型调用和检索器，并要求每个回答都列出引用的文章编号。
结果：在自建的 60 条测试问题上，检索前 5 名命中正确文章的比例为 52/60。
相关能力：RAG, LangChain, vector search, pgvector, PostgreSQL, prompt design, evaluation.

## 我的工作 后端接口与前端页面
我用 FastAPI 写了问答、反馈和文章管理三组接口，用 React 做了一个简单的对话页面，用户可以对回答点赞或点踩，反馈写入数据库用于后续改进。整个系统用 Docker Compose 在本机一键启动。
结果：完成可演示的端到端系统，接口有 41 项 pytest 测试。
相关能力：FastAPI, REST API, React, Docker Compose, pytest, full-stack development.

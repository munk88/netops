# netops-mvp 知识库

把**排障手册、命令手册、配置规范**等运维文档放进这个目录（`.md` / `.txt` / `.rst`），
Agent 启动时会自动读取并建立索引，`search_kb` 工具就能检索到它们。

## 怎么加知识

1. 把文档（Markdown 优先）丢进本目录，可建子目录分类
2. 重启 Agent，或执行重建命令：
   ```bash
   ./.venv/bin/python -m netops_agent.rag --rebuild
   ```
3. 验证检索：
   ```bash
   ./.venv/bin/python -m netops_agent.rag --query "接口 down 怎么处理"
   ```

## 建议的文档组织

- 按主题一份文档一个文件（如「接口 down 排障」「OSPF 排障」）
- 每个主题用标题分段，Agent 按段落切块，来源会标到「文件名」
- 保持命令示例准确，格式规范，便于检索

## 说明

- 目录为空 / 不存在时，自动回退到内置示例知识
- 检索实现目前是 TF-IDF（零重依赖），接口与真实向量库对齐，后续可无缝升级

# Repository Guidelines

## 项目结构与模块组织

本仓库用于构建并记录聚合物 fragment 词表流程。核心脚本位于 `scripts/`，当前主要入口是 `scripts/build_fragment_vocab_v1.py`。原始输入数据为 `data/all_polymers_experiment_final.csv`；规范化记录和 graph 产物写入 `data/processed/`。fragment 相关产物按生命周期放在 `fragments/seeds/`、`fragments/mining/`、`fragments/vocab/` 和 `fragments/validation/`。规格说明、schema 参考和验证计划放在 `docs/`，静态图片放在 `images/`。

## 构建、测试与开发命令

- `python scripts/build_fragment_vocab_v1.py`：重新生成 processed 数据、seed 规则、mined motifs、词表 JSON/JSONL 文件和验证报告。
- `python scripts/build_fragment_vocab_v1.py --summary`：运行同一流水线，并在终端输出 build summary JSON。
- `git status --short`：提交前检查脚本和生成产物的变更范围。

脚本依赖 RDKit。如果本地存在 `.codex_py_deps/`，脚本会自动将其加入 `sys.path`。

## 编码风格与命名约定

使用 Python 3、四空格缩进、类型标注和 `pathlib.Path`。优先把可复用逻辑拆成小型 helper 函数。涉及可复现产物时，JSON/JSONL 写入应保持稳定排序。Python 函数和变量使用 lowercase `snake_case`，共享路径和配置常量使用大写命名。版本化产物文件名应稳定，例如 `fragment_vocab_v1.0.jsonl`。包含中文字段名的数据文件必须保持 UTF-8 编码。

## 测试指南

当前尚无正式测试套件。现阶段把构建脚本作为回归检查：修改逻辑或数据 schema 后，运行 `python scripts/build_fragment_vocab_v1.py --summary`，并检查 `fragments/fragment_vocab_v1.0.build_summary.json` 与 `fragments/validation/fragment_vocab_v1.0.validation_report.md`。新增测试时优先使用 `pytest`，测试文件放在 `tests/`，命名为 `test_*.py`。

## 提交与 Pull Request 规范

当前 Git 历史使用简短的祈使句提交标题，例如 `Add warmup planning docs`。提交标题应简洁、动作明确。Pull Request 需要说明对数据或流水线的影响，列出重新生成的产物，注明 RDKit 或依赖假设，并链接 `docs/` 中相关规划文档。修改 matching、canonicalization 或 validation 行为时，应提供变更前后的 summary counts。

## 数据与生成产物注意事项

除非是在记录明确的人工修正，否则不要手动编辑生成的 JSON/JSONL 报告。优先修改脚本或 seed 规则后重新生成输出，确保 `data/processed/`、`fragments/vocab/` 和 `fragments/validation/` 保持可复现。

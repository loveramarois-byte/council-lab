# 传统文化资料来源审计

更新时间：2026-08-02

这份审计回答一个容易混淆的问题：上游项目是否真的提供了可直接打包的古籍原文。Council Lab 当前不把书名索引、规则摘要、精选片段或网页编译产物统称为“原文”。

## 四个上游项目

| 项目 | 实际内容 | Council Lab 当前处理 | 固定来源 |
| --- | --- | --- | --- |
| [lunar-javascript](https://github.com/6tail/lunar-javascript/tree/4c45a59f79b856125516f31aefa8295035c16af) | 公农历、节气、干支、八字等计算引擎；没有本项目需要的古籍正文 | 作为本地计算引擎，不作为典籍资料 | [MIT](https://github.com/6tail/lunar-javascript/blob/4c45a59f79b856125516f31aefa8295035c16af/LICENSE) |
| [bazi-skill](https://github.com/jinchenma94/bazi-skill/tree/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c) | `classical-texts.md` 是九部典籍的规则摘要、口诀示例和解释框架，不是经校勘的完整原文 | 允许标为“上游规则摘要”，不注入模型上下文，不当作引文 | [MIT](https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/LICENSE) |
| [ziwei-doushu](https://github.com/Renhuai123/ziwei-doushu/tree/88194a404242bfe5c6d5cc512e4117e3e245cdd5) | `lib/classics/data/` 有《骨髓赋》《紫微斗数全集》《紫微斗数全书》的结构化精选片段；文件注释自己也写明部分内容是精选，且声称的全书字数不等于文件实际字数 | 《紫微斗数全书》可标为“上游精选片段”，不称完整原文 | [MIT](https://github.com/Renhuai123/ziwei-doushu/blob/88194a404242bfe5c6d5cc512e4117e3e245cdd5/LICENSE) |
| [iztro](https://github.com/SylarLong/iztro/tree/2fb203040b00d87f2fa240f6109511d350ca502b) | `docs/learn/ancientBook-*.html` 含整理后的古籍阅读页，但主要是构建产物，版本、底本、整理责任和逐段出处需要另行核对 | 只作为外部阅读参考，不复制进发行包 | [MIT](https://github.com/SylarLong/iztro/blob/2fb203040b00d87f2fa240f6109511d350ca502b/LICENSE) |

## 为什么现在不直接把“原文”塞进模型

1. 全文塞进每次 Prompt 会增加 Token、延迟和费用，还会让模型把不同版本混成一个答案。
2. “古籍原文”需要底本、卷章、版本、整理者和段落定位；没有这些字段，用户无法复核引文。
3. 上游代码采用 MIT，不自动证明其中每一段第三方古籍整理内容都没有额外的版本或出版限制。
4. 传统解释不是事实核验。即使文本来源可靠，也不能把古籍观点升级成医疗、法律、投资、合规或生产结论。

## 当前产品行为

- `仅索引`：只保存书名、主题和流派。
- `上游规则摘要`：有固定 commit 的上游链接，但不是原文。
- `上游精选片段`：有固定 commit 的代码文件链接，但不是完整古籍。
- 三种状态都会进入选择界面、冻结模型上下文和 Markdown/HTML 导出；模型不会看到未明确载入的书文。

## 下一步的正确实现方式

如果后续加入可再分发的原文资料包，应使用独立的、可关闭的本地资料层，而不是把全文拼到 Prompt：

1. 每个资料包记录底本、卷章、整理者、许可证、上游 commit、文件 SHA-256 和段落 ID。
2. 只检索与当前研究主题匹配的短段落，并把段落 ID、版本和来源链接一起传给模型。
3. 最终答案只能引用真实载入的段落；没有段落证据时必须写“未载入原文”。
4. 资料包与桌面安装包分离，允许用户只安装计算引擎，或自行导入拥有授权的版本。
5. 对用户导入的资料做大小、格式、路径和提示注入隔离，原文内容一律视为不可信数据。

在完成底本与授权核验前，Council Lab 不会把上游摘要或网页编译产物宣传成“内置古籍原文”。

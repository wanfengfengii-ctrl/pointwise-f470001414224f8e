# 已签发样品的撤回复核

白班的具名记录、冻结修订、V1 站件及原签发仍按 README.md 工作。撤回复核针对一个既有成果的原父件、原样品顺序及原接口。复核会另存结论，原成果、回执和摘录可照常领取。原签发流程继续使用 V1 资格。

## 发行与投递

实现以下公开 Python 入口。`db` 使用原项目的源库或夜班库连接。可在已有库反复初始化，原表中的业务资料继续保留。

- `publish.withdrawal_sheet(db, revision_key)` 从已经出版的确切修订发行固定复核附页，返回 JSON 文本。`revision_key` 沿用 `(station, batch, revision)`。同一已出版修订重复取得同一附页，源库重开及后续修订均不改变它。
- `publish.withdrawal_notice(db, revision_key, notice_id, record_ids)` 返回独立通知的 JSON 文本。`record_ids` 接受非空的记录 ID 列表、元组或集合，按集合解释。每个 ID 须属于指定冻结修订，包含与任何公开端点无连接的记录。通知引用该修订的固定附页。可先取得通知再领取附页，送达夜班时先接纳附页。缺出版抛 `LookupError`，非法参数或未知原记录抛 `ValueError`。
- `review.import_withdrawal_sheet(db, payload)` 从 JSON 文本或 UTF-8 字节接纳附页，返回 `pack_id`。对应 V1 件须已接纳，且内容摘要须匹配。同一附页可以重投。同父件只能接纳一份固定附页。
- `review.import_withdrawal_notice(db, payload)` 从 JSON 文本或 UTF-8 字节接纳通知，返回 `(pack_id, notice_id)`。夜班以父件及通知号认领。重投相同别名集合返回原身份。同身份异集合拒绝。不同通知可以撤回同一别名，后续复核保留这些已接纳通知各自的身份。

附页和通知使用独立于 V1 的 JSON 对象。标识符同 V1，区分大小写并保留原字符。`version` 均为整数 `1`。附页字段如下。

| 字段 | 内容 |
| --- | --- |
| `kind` | `withdrawal-sheet` |
| `version` | `1` |
| `pack_id` | 原 V1 站件号 |
| `pack_sha256` | `publish.encode_package` 规范化后的 V1 文本的 UTF-8 SHA-256，小写十六进制 |
| `aliases` | 原修订每笔记录对应一个不同的非空白文本别名，数组按文本升序 |
| `response` | 撤回后的公开资格响应，表示由交付方定义并随实现说明 |

通知恰含 `kind`（`withdrawal-notice`）、`version`、`pack_id`、`sheet_sha256`、`notice_id` 和 `aliases`。`sheet_sha256` 是附页整个对象按 `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)` 序列化后的 UTF-8 SHA-256，小写十六进制。通知的 `aliases` 为非空数组，按集合解释。文本的空白和对象字段顺序不影响认领。别名只在该固定附页内有意义。另一修订中的同名记录有独立作用域。

原记录号、内部节点、带内部端点的图以及逐条路线均留站。可以公开为判定所必需的匿名关系。附页须覆盖原 V1 的全部单件和双件资格，空撤回与 V1 一致，任意累计撤回与在固定站内修订中去掉这些记录后的资格一致。夜班接纳时检查封套、父件绑定、别名引用及所选响应格式的结构，检查空撤回与原资格一致。站端是资格事实的可信发行者，摘要用于认领内容，业务无需消息签名。

缺少相应的已接纳原件或附页时抛 `LookupError`。格式错误、重复 JSON 对象键、身份或摘要冲突、未知别名、无效响应抛 `ValueError`。拒收后原附页及原通知集合保持原样。SQLite 写入和提交失败沿用原异常及回滚约定。

## 复核与领取

`results.review_withdrawals(db, result_id)` 只凭夜班库工作。对原成果的两个父件分别取当前已接纳通知的撤回并集。没有通知的父件沿用原 V1 资格，允许它没有附页。缺成果或两个原父件均无已接纳通知时抛 `LookupError`。同批其他修订及其他站件的通知不参与。

使用原成果对应的站内有向端点关系。单件仍须有非空连续出处。双件须存在一对各自满足端点且互不共用原记录的有效出处。公开关系相同的两件仍算两件。两站都在原接口上维持原资格才通过。另一个接口可签时仍按原接口作结论。

`results.review_withdrawals` 返回新提交的 JSON 兼容字典。`results.fetch_withdrawal_review(db, review_id)` 按独立的正整数复核号返回同一字典，缺号抛 `LookupError`。字典具有以下字段。

| 字段 | 内容 |
| --- | --- |
| `review_id` | 本次复核号 |
| `result_id` | 原 V1 成果号 |
| `parents` | 前站、后站的原 `ParentRef` 字典，各含 `pack_id`、`station`、`batch`、`revision` |
| `samples` | 原顺序的 `SampleRequest` 字典，各含 `sample_id`、`start`、`end` |
| `interfaces` | 按原样品顺序的接口数组 |
| `notices` | 采用的全部通知，各为 `{ "pack_id": ..., "notice_id": ... }`，按这两个字段依次以文本排序 |
| `status` | `valid` 或 `invalid` |

`valid` 和 `invalid` 都是可领取的业务结论。每次复核保存该次的固定快照。提交失败无新增复核，可再次提交。后到通知可用于下一次复核，已有复核读回固定快照。允许全量计算和复用现有事务。

## 样例与交付核验

`withdrawal_cases.py` 提供两个制样站对照。`private-r` 和 `private-s` 都连接 `a1` 到 `p`。`spare=True` 时 `private-t` 也连接这两个端点，`spare=False` 时它在隔离区。两份 V1 站件字节相同，原双件绑定均为 `(p,q)`。分别只收 `private-r` 或 `private-s` 的撤回时，原绑定均为 `valid`。两份通知齐备时，只有 `spare=True` 的原绑定仍为 `valid`。另一份为 `invalid`，即使重新签发可以选 `(q,q)`。通知逆序到达，或其中一份重复投递，均得到同样的结论和通知身份集合。另一个夹具的两件都须经过 `r1` 或 `r2`，撤回 `r1` 后各自仍可查，合查为 `invalid`。

`python3 -B withdrawal_cases.py` 以 V1 的原入口与去掉记录后的站内参考重算核对这些输入。实现后沿 `.pointwise-runtime.json` 的 `verify` 保留完整原回归并核验新链，包括父件隔离、原接口裁决、回滚及固定复读。沿 `demo` 展示断源后逐份接纳、累积前后不同结论，以及重开领取两次复核和原成果。说明所选响应的完备性、别名作用域及通知身份如何交给夜班。

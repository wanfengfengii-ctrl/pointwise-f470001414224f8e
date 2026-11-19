# 澄桥样品流转档案 V1

澄桥材料试验中心白班按交接单登记实物的流转。站内归档员关账并发布站件，夜班凭两份指定站件核定样品出处，次班按成果号领取和导出固定摘录。站内记录和内部节点由各站留存。系统使用 Python 3.11 标准库与 SQLite。

## 一天的交班

1. 白班在各站的源库按站、日批、草稿登记节点。
2. 录入员按编号登记有向交接。同号同端点重报返回原记录，同号改端点拒绝。同端点异编号分别入账。
3. 归档员提交公开端点目录。校验覆盖站内全图，包括与站界无连接的记录。冻结快照与草稿关账一起生效。
4. 按确切冻结修订发布固定站件。重取返回原载荷。
5. 夜班在独立库接纳双方的 V1 站件，包括独立制作的合法站件。
6. 核验员按原顺序提交一件或两件样品。两份父件必须同批、不同站且有互认的出入接缝。
7. 核验通过后，成果、固定出处和回执一起提交。拒签和写入失败无新增成果或成功回执。
8. 次班可从指定冻结修订开启独立草稿，更正后发布新修订。关闭来源并重开夜班库后，旧号仍可取得原成果和摘录。

## 计算口径

站内一件样品须有一条包含至少一笔具名记录的连续有向链。双件须存在一对分别满足端点的链，且两链使用的原记录编号集合不相交。节点可以共享，同内容异编号的记录独立。两件可以走同一公开接口，只要两站都允许该绑定。接缝由前站指向后站的 `out` 点和后站指向前站的同名 `in` 点组成。每件在两站使用自己的同一个接口。多个绑定共同成立时，按请求次序组成完整接口元组并取文本字典序首项，例如 `p10` 排在 `p2` 前。身份为区分大小写的非空白 Unicode 文本。比较使用原字符，无数字转换、舍入或随机选择。

## Python 接口

`intake.open_source(path)` 和 `results.open_night(path)` 打开并初始化各自的 SQLite 库。调用方负责关闭连接。`intake.initialize_source(db)` 与 `results.initialize_night(db)` 可重复调用，保留用户录入、修订、出版、接纳、成果和回执。公开写入操作使用这些入口返回的连接，调用时应无外层事务。分模块的底层写入函数供所属业务事务调用。

- `intake.create_draft(db, station, batch, draft)` 创建草稿。后续草稿键为 `(station, batch, draft)`。`intake.add_node(db, key, node)` 登记节点，`intake.record(db, key, record_id, start, end)` 返回包含身份与端点的 `Transfer`。草稿中的记录可用 `intake.withdraw_record(db, key, record_id)` 撤下后更正。关闭草稿拒绝修改。
- `freeze.close_day(db, key, revision, boundaries)` 返回冻结修订。目录项用 `freeze.BoundaryPoint(public_id, node, direction='local', neighbor=None)`。公开编号在目录内唯一，节点须属于该草稿。`local` 的邻站为空，`in` 和 `out` 的邻站须为另一站。`freeze.open_successor(db, (station, batch, revision), draft)` 复制指定修订的节点和记录到独立草稿，关账时提交新目录。
- `publish.publish_pack(db, (station, batch, revision))` 返回固定 UTF-8 JSON 载荷文本。`publish.read_publication` 读取已出版的同一载荷，`publish.decode_package` 查看公开元数据和资格。
- `review.import_pack(db, payload)` 接受 UTF-8 字节或 JSON 文本并返回站件号。相同内容可以重报。`review.ReviewRequest(front_id, rear_id, samples)` 中 `samples` 是一项或两项 `review.SampleRequest(sample_id, start, end)` 组成的元组，样品号互异，端点分别来自指定前后站公开目录。
- `results.issue(db, request)` 返回正式 `IssuedResult`，包含成果号、两份父件、原请求顺序、逐项绑定和回执。`results.fetch(db, result_id)` 与 `results.export_excerpt(db, result_id)` 按整数成果号读回原快照和 JSON 摘录。

业务拒绝使用带稳定消息的 `ValueError` 或 `LookupError`。例如 `RECORD_CONFLICT`、`ENDPOINT_NOT_IN_DRAFT`、`INVALID_BOUNDARY`、`CYCLIC_DAY`、`INVALID_PACKAGE`、`INVALID_EVIDENCE`、`PACKAGE_ID_CONFLICT`、`MIXED_BATCH`、`NON_ADJACENT`、`INVALID_REQUEST`、`NO_COMMON_EVIDENCE` 和 `RESULT_NOT_FOUND`。SQLite 写入及提交失败保留原异常并回滚本次写入。两个站件有非空的互认接缝时，只在这些共同接口中寻找绑定。

## 独立 V1 站件

V1 是 UTF-8 JSON 对象。顶层必填字段为 `version`、`id`、`station`、`batch`、`revision`、`boundaries`、`eligibility`。`version` 是整数 `1`，其余四个身份为文本。目录项恰含 `id`、`direction`、`neighbor`，方向及邻站规则与源端相同。`eligibility` 恰含 `singles` 与 `pairs` 两个数组，可以为空。单件项是两个不同的公开端点组成的有向关系。双件项由两条已有单件资格的有向关系组成，两条关系可相同。双件内交换整条关系保持同一个站内事实，关系内部的端点方向保持原义。条目排列和重复事实不改变内容。字段集固定，JSON 对象内的键须唯一。接纳端验证结构、公开引用与资格一致性，发布者负责核定事实的原始出处。

下例可由站内两条独立记录 `a→p` 与 `b→q` 形成。站件只携带公开事实。

```json
{
  "version": 1,
  "id": "external-prep-1",
  "station": "prep",
  "batch": "day-01",
  "revision": "R1",
  "boundaries": [
    {"id": "a", "direction": "local", "neighbor": null},
    {"id": "b", "direction": "local", "neighbor": null},
    {"id": "p", "direction": "out", "neighbor": "lab"},
    {"id": "q", "direction": "out", "neighbor": "lab"}
  ],
  "eligibility": {
    "singles": [["a", "p"], ["b", "q"]],
    "pairs": [[["a", "p"], ["b", "q"]]]
  }
}
```

## 核验和演示

项目物化后，在项目根目录运行完整回归和演示。

```sh
python3 -B check_project.py
python3 -B demo.py
```

控制台提供 `check_project.py`。标准库直接发现完整套件的命令为 `python3 -B -m unittest discover -s tests -t . -p 'test_*.py'`。测试使用临时 SQLite 库，覆盖同号重报与冲突、隔离环、平行记录及替代链、手制站件的顺序与同接口绑定、拒签、真实回执写入失败和更正后的原版复读。演示在临时目录创建两个来源、发布并关闭来源，展示共用原记录时两项单查成功而双查拒签，以及换为两条独立记录后双查签发和重开领取。

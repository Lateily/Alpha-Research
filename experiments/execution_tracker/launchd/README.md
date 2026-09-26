# launchd 运行时(新克隆复现指南)

审计 MAJOR(2026-08-01):此前 `ar_env_wrapper.sh` 未入库,本机三个 launchd 任务全部
依赖它,新克隆无法复现运行环境。现补齐 wrapper + 三份**去密钥**plist 模板。

## 安装

```bash
# 1. 凭证保险箱(600 权限,永不进 git)
umask 077 && printf 'export TUSHARE_TOKEN=<你的token>\n' > ~/.ar_env && chmod 600 ~/.ar_env

# 2. 从模板生成 plist(把 __HOME__ 换成真实家目录)
for t in com.ar.nightly com.ar.watchtower com.ar.eod; do
  sed "s|__HOME__|$HOME|g" experiments/execution_tracker/launchd/$t.plist.template \
    > ~/Library/LaunchAgents/$t.plist
  launchctl unload ~/Library/LaunchAgents/$t.plist 2>/dev/null
  launchctl load  ~/Library/LaunchAgents/$t.plist
done
```

Macro OS M0-B3 使用单独的 5 分钟守护入口。**只有在 M0-B2 与 M0-B3 都合并、
运行目录安全同步、release calendar 已发布并完成一次沙箱验收后**才安装:

```bash
sed "s|__HOME__|$HOME|g" \
  experiments/execution_tracker/launchd/com.ar.macro-os.plist.template \
  > ~/Library/LaunchAgents/com.ar.macro-os.plist
launchctl load ~/Library/LaunchAgents/com.ar.macro-os.plist
```

launchd 每 5 分钟唤醒一次,但程序会读取 `scheduler_status.next_check_at` 自适应
跳过未到期轮次。它不会每 5 分钟都访问数据源。当前模板仅交付、未安装,
所以 M0-B3 状态是 `DELIVERED_UNWIRED`。

## 设计约束
- **密钥不进 plist**:所有任务经 `ar_env_wrapper.sh` 启动,由它 source `~/.ar_env`
  再 exec 目标命令。模板已剥离全部 TOKEN/KEY/SECRET 字段。
- 路径以 `__HOME__` 占位,安装时替换 —— 模板可安全入库。
- 机器必须唤醒且联网(本地设计 v0);夜链失败会落 `/tmp/ar-nightly-incomplete` 报警旗。
- Macro OS 当前只写面板契约和风险预算上下文,不发微信提醒,不拥有直接阻断权。
- **launchd 按本机时区触发,程序按 Asia/Shanghai 判时段**(2026-09 伦敦时钟事故,
  `market_clock.py`)。本机不在 UTC+8 时,watchtower(09:14 本地)与 eod(14:26 本地)
  落在上海盘后,会打印 `OUTSIDE_MARKET_HOURS` 并以退出码 3 结束,不读行情、不写
  nowcast / eod_candidates;非交易日打印 `NON_TRADING_DAY`,退出码 0。
  `launchctl list | grep com.ar` 的末次退出码 3 = 调度与上海时段错位,需改调度或时区。
  夜链(20:30 本地)在两种时区下都在收盘后,伦敦时钟下落在北京次日 03:30
  (BST;10-25 转 GMT 后为 04:30)。

不是买卖指令;研究信号,human executes.

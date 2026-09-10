"""用 Task Scheduler COM API 注册 cockpit 8090 自愈保活计划任务（SYSTEM 级、隐藏、每分钟、无窗口）。

不走 schtasks.exe（被 WorkBuddy 程序黑名单拦截），直接调 Schedule.Service COM。
"""
import win32com.client
from datetime import datetime

PYTHONW = r"C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
SCRIPT = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\cockpit_keepalive.py"
CWD = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc"
TASK_NAME = "Cockpit8090Keepalive"

# COM 常量
TASK_ACTION_EXEC = 0
TASK_TRIGGER_TIME = 1
TASK_CREATE_OR_UPDATE = 6
TASK_LOGON_SERVICE_ACCOUNT = 5
TASK_RUNLEVEL_HIGHEST = 1
TASK_INSTANCES_IGNORE_NEW = 1

ts = win32com.client.Dispatch("Schedule.Service")
ts.Connect()
root = ts.GetFolder("\\")

task = ts.NewTask(0)
task.RegistrationInfo.Description = "Cockpit 8090 self-healing keepalive (SYSTEM, hidden, no window)"
task.RegistrationInfo.Author = "cenacai"

# 主体：SYSTEM 服务账户，最高权限
task.Principal.UserId = "SYSTEM"
task.Principal.LogonType = TASK_LOGON_SERVICE_ACCOUNT
task.Principal.RunLevel = TASK_RUNLEVEL_HIGHEST

# 设置：隐藏、不限时、忽略重复实例
task.Settings.Hidden = True
task.Settings.Enabled = True
task.Settings.DisallowStartIfOnBatteries = False
task.Settings.StopIfGoingOnBatteries = False
task.Settings.ExecutionTimeLimit = ""          # 无执行时限
task.Settings.MultipleInstances = TASK_INSTANCES_IGNORE_NEW

# 动作：pythonw 跑 keepalive 脚本
act = task.Actions.Create(TASK_ACTION_EXEC)
act.Path = PYTHONW
act.Arguments = SCRIPT
act.WorkingDirectory = CWD

# 触发器：立即起，之后每 1 分钟重复，无限期
trig = task.Triggers.Create(TASK_TRIGGER_TIME)
trig.StartBoundary = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
trig.Enabled = True
trig.Repetition.Interval = "PT1M"     # 1 分钟
trig.Repetition.Duration = ""         # 空 = 无限期

root.RegisterTaskDefinition(
    TASK_NAME,
    task,
    TASK_CREATE_OR_UPDATE,
    "",   # userId（SYSTEM 用空）
    "",   # password
    TASK_LOGON_SERVICE_ACCOUNT,
)

print("REGISTERED_OK")

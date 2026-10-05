@echo off
rem Windows 计划任务入口（每天 12:00）。ZCode 定时不可用时的系统级兜底：
rem   schtasks /create /tn "AI爆款日报" /tr "D:\自动信息流agent\task.cmd" /sc daily /st 12:00
rem 注意：本入口只做 采集+规则分（无LLM评审），产出兜底版日报看板。
cd /d %~dp0
if not exist logs mkdir logs
python src\main.py all --no-open >> logs\task.log 2>&1

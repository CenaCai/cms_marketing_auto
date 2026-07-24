@echo off
cd /d C:\Users\cenacai\WorkBuddy\2026-07-16-12-05-32\mautic-prod
C:\Users\cenacai\.workbuddy\php82nts\php.exe bin/console mautic:segments:update
C:\Users\cenacai\.workbuddy\php82nts\php.exe bin/console mautic:campaigns:rebuild
C:\Users\cenacai\.workbuddy\php82nts\php.exe bin/console mautic:campaigns:trigger

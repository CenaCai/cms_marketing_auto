FROM python:3.13-slim

WORKDIR /app

# 零第三方依赖：仅标准库 + 同目录模块（goal_intake / plan_compiler / mautic_client ...）
COPY . /app
RUN chmod +x docker/entrypoint.sh

EXPOSE 8090
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# W5 演练线实测读数归档

- 演练时间：2026-09-21 10:37~10:41（容器日志为 UTC 02:37~02:41）
- 拓扑基线：W4 staging 栈原地增量（etcd/patroni×2/api/worker/web 连续运行未动，`Up 3 days`），仅新增 minio/init-minio 与 pgbackrest 依赖链重建
- 相关 commit：staging-drill.md（W4 主从切换）/ 本文件 T14 段（MinIO + pgbackrest 迁 S3）

## T14 — MinIO + pgbackrest 迁 S3（EDP-031 前置）

- 改动：`deploy/docker-compose.staging.yml` 新增 minio（S3 API :19000 / console :19001，命名卷 minio-data）与 init-minio 一次性 job；`deploy/pgbackrest/pgbackrest.conf` repo1 迁 S3（W4 本地 repo 卷保留为降级预案）；新增 `deploy/scripts/init-minio.sh`（幂等建 bucket）。
- 演示凭据：`edp_minio` / 32 hex 随机密码（compose 与 pgbackrest.conf 同值，注释「演示值，生产经 secret manager」）。

### 镜像与版本（实测拉取可用）

- minio：`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`（digest sha256:14cea493...；镜像内含 curl/mc，healthcheck 用 `curl -fsS /minio/health/ready`）
- mc：`quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z`（`mc version RELEASE.2025-08-13T08-35-41Z`，go1.24.6）
- pgbackrest：2.59.1（自建 patroni 镜像内，未变）

### 关键实测发现：endpoint 必须带 http:// 前缀

pgbackrest 2.59.1 对 S3 默认强制 TLS——`repo1-s3-verify-ssl=n` 只跳过证书校验、不降级为明文。实测（CLI 临时 conf，不动挂载配置）：

    # endpoint=minio:9000（无 scheme）+ verify-ssl=n → 仍走 TLS：
    stanza: edp
        status: error (other)
                [ServiceError] TLS error [1:167772427] wrong version number

    # endpoint=http://minio:9000 → 明文 http，bucket 查询成功：
    stanza: edp
        status: error (missing stanza path)   # bucket 在、stanza 未建，符合预期

结论：内网 MinIO 明文方案须写 `repo1-s3-endpoint=http://minio:9000`（另需 `repo1-s3-uri-style=path`，MinIO 不支持 vhost-style）。

### 增量上栈与 bucket 初始化

`docker compose up -d minio init-minio`（未触碰既有 7 容器）；minio healthcheck 通过后 init job 输出：

    Bucket created successfully `local/edp-backups`.
    [2026-09-21 02:37:39 UTC]     0B edp-backups/

二次 up（幂等重跑，`--ignore-existing`）退出码 0。`up -d pgbackrest` 依赖链实测：minio Healthy → init-minio Exited(0) → pgbackrest 就绪。

### stanza-create（真实 conf，幂等）

~~~
2026-09-21 02:40:25.213 P00   INFO: stanza-create command begin 2.59.1: --exec-id=52375-ba0a8d53 ... --repo1-s3-endpoint=http://minio:9000 ... --repo1-type=s3 --stanza=edp
2026-09-21 02:40:25.226 P00   INFO: stanza-create for stanza 'edp' on repo1
2026-09-21 02:40:25.232 P00   INFO: stanza 'edp' already exists on repo1 and is valid
2026-09-21 02:40:25.232 P00   INFO: stanza-create command end: completed successfully (47ms)
~~~
（首次建 stanza 在验证 http:// 前缀时已完成，100ms，输出同形）

### 全量备份 → S3（实测）

`docker compose exec patroni1 pgbackrest --stanza=edp --type=full backup`：

~~~
2026-09-21 02:40:31.981 P00   INFO: backup command begin 2.59.1: ... --repo1-s3-bucket=edp-backups --repo1-s3-endpoint=http://minio:9000 ... --type=full
2026-09-21 02:40:32.009 P00   INFO: execute backup start: backup begins after the next regular checkpoint completes
2026-09-21 02:40:32.410 P00   INFO: backup start archive = 000000070000000000000009, lsn = 0/9000028
2026-09-21 02:40:41.521 P00   INFO: execute backup stop and wait for all WAL segments to archive
2026-09-21 02:40:41.597 P00   INFO: backup stop archive = 000000070000000000000009, lsn = 0/9000138
2026-09-21 02:40:41.678 P00   INFO: new backup label = 20260921-024032F
2026-09-21 02:40:41.802 P00   INFO: full backup size = 32.3MB, file total = 1565
2026-09-21 02:40:41.802 P00   INFO: backup command end: completed successfully (9902ms)
2026-09-21 02:40:41.802 P00   INFO: expire command begin 2.59.1: ...（retention-full=2）
2026-09-21 02:40:41.809 P00   INFO: expire command end: completed successfully (7ms)
~~~

- 备份集：**32.3MB / 1565 文件 / 压缩后 4.1MB**
- 执行时长：**9.9s**（pgbackrest 计时；宿主 wall clock 10.6s）
- 对比 W4 本地卷全量：同数据 32.3MB / 8.5s → S3 链路增加 ~1.4s（内网 MinIO，可接受）

### WAL 归档往返（check 实测）

~~~
2026-09-21 02:41:10.170 P00   INFO: check command begin 2.59.1: ...
2026-09-21 02:41:10.181 P00   INFO: check repo1 configuration (primary)
2026-09-21 02:41:10.205 P00   INFO: check repo1 archive for WAL (primary)
2026-09-21 02:41:10.510 P00   INFO: WAL segment 00000007000000000000000A successfully archived to '/pgbackrest/edp/archive/edp/16-1/0000000700000000/00000007000000000000000A-ae818ab023ec36367f72f011f8f871e3b2a5f660.gz' on repo1
2026-09-21 02:41:10.510 P00   INFO: check command end: completed successfully (348ms)
~~~

### pgbackrest info（repo keeper 容器，`-u postgres`）

~~~
stanza: edp
    status: ok
    cipher: none

    db (current)
        wal archive min/max (16): 000000070000000000000008/000000070000000000000009

        full backup: 20260921-024032F
            timestamp start/stop: 2026-09-21 02:40:32+00 / 2026-09-21 02:40:41+00
            wal start/stop: 000000070000000000000009 / 000000070000000000000009
            database size: 32.3MB, database backup size: 32.3MB
            repo1: backup set size: 4.1MB, backup size: 4.1MB
~~~

注：S3 repo 的 WAL 区间从 timeline 7 `...0008` 起（此前段落归档在 W4 本地 repo 卷）；PITR 基线以 S3 首个全量 20260921-024032F 为准。

### S3 对象存储读数（mc）

    $ mc du local/edp-backups
    4.8MiB	1576 objects	edp-backups
    $ mc ls local/edp-backups/pgbackrest/edp/
    [2026-09-21 02:41:27 UTC]     0B archive/
    [2026-09-21 02:41:27 UTC]     0B backup/

- 对象数：**1576**（备份集 1565 文件 + WAL/manifest 索引等）；占用 **4.8MiB**；结构 `pgbackrest/edp/{archive,backup}`
- console：宿主浏览器 http://localhost:19001（edp_minio / 演示密码）

## 结论与降级预案

1. **对象存储备份链路实测成立，未触发降级**：MinIO 起 → bucket 幂等初始化 → stanza-create → 全量备份 → WAL 推取往返（check）→ info/mc du 读数全部真跑通过；既有 7 容器（含 api/worker/web）零重启零中断。
2. **patroni 容器无需重启**：pgbackrest.conf 为只读 bind mount，宿主改写即热生效（archive_command 每次调用重读配置），S3 迁移对主从零扰动。
3. **降级预案（未触发，凭据已验在位）**：MinIO 不可用/资源不足时，将 pgbackrest.conf `[global]` 改回 `repo1-path=/pgbackrest/repo` 并删除 `repo1-type`/`repo1-s3-*` 各行（backups 卷仍挂载，W4 本地备份集实测仍在：`/pgbackrest/repo` 13M，含 20260918-002007F 全量）。
4. **已知取舍（记入后续项）**：内网明文 http（演示形态，生产走 TLS + secret manager 注入凭据）；MINIO_ROOT_USER 复用为 repo1-s3-key（生产应为独立最小权限 service account）；单副本 MinIO 无纠删码，对象存储冗余待 EDP-031 正式选型。

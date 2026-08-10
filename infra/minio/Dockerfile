# syntax=docker/dockerfile:1.18@sha256:dabfc0969b935b2080555ace70ee69a5261af8a8f1b4df97b9e7fbcf6722eddf

FROM golang:1.24.8-alpine3.22@sha256:3d78beb141d98f42337f1252ecf2a5f20374109929a4c3f6817f9e4179cc0ae5 AS build

ARG MINIO_COMMIT=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a
ARG MINIO_SOURCE_SHA256=45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z

ENV CGO_ENABLED=0 \
    GOFLAGS=-mod=readonly \
    GOPATH=/go

WORKDIR /build

RUN wget -q -O source.tar.gz "https://github.com/minio/minio/archive/${MINIO_COMMIT}.tar.gz" \
    && echo "${MINIO_SOURCE_SHA256}  source.tar.gz" | sha256sum -c - \
    && tar -xzf source.tar.gz --strip-components=1 \
    && test "$(sed -n 's/^toolchain //p' go.mod)" = "go1.24.8"

RUN go mod download \
    && go mod verify \
    && go build \
      -tags kqueue \
      -trimpath \
      -ldflags "-s -w -buildid= -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.CopyrightYear=2025 -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_RELEASE} -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648 -X github.com/minio/minio/cmd.GOPATH=/go -X github.com/minio/minio/cmd.GOROOT=/usr/local/go" \
      -o /out/minio ./

FROM alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1

LABEL org.opencontainers.image.title="MinIO local development build" \
      org.opencontainers.image.description="Loopback-only synthetic-data MinIO build; not approved for production" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.version="RELEASE.2025-10-15T17-29-55Z" \
      org.opencontainers.image.source="https://github.com/minio/minio"

ENV MINIO_ROOT_USER_FILE=/run/secrets/minio_root_user \
    MINIO_ROOT_PASSWORD_FILE=/run/secrets/minio_root_password \
    MINIO_UPDATE=off \
    MINIO_CONFIG_ENV_FILE=/dev/null

RUN addgroup -S -g 10001 minio \
    && adduser -S -D -H -u 10001 -G minio minio \
    && mkdir -p /data /licenses \
    && chown -R 10001:10001 /data

COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build --chmod=0755 /out/minio /usr/local/bin/minio
COPY --from=build /build/LICENSE /licenses/LICENSE
COPY --from=build /build/CREDITS /licenses/CREDITS

USER 10001:10001
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--address", ":9000", "--console-address", ":9001"]

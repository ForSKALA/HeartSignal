# HeartSignal 인증 서버 (Java HttpServer :8080)
# gradle-wrapper.jar는 .gitignore(*.jar)로 저장소에 없으므로 gradle 이미지의 gradle 명령으로 빌드한다.

# 1) 빌드 단계
FROM gradle:9.0.0-jdk17 AS build
WORKDIR /src
COPY . .
RUN gradle :app:installDist --no-daemon

# 2) 실행 단계
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /src/app/build/install/app/ /app/

EXPOSE 8080

# k8s env로 오버라이드 가능: - name: JAVA_OPTS
CMD ["sh", "-c", "exec /app/bin/app"]

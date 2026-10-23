# HeartSignal 화면 (nginx :80)
# 빌드 컨텍스트 = 저장소 루트 (web/docker-build.sh 참고). 정적 파일만 서빙하므로 별도의 빌드 단계가 없다.
FROM nginx:alpine

# 기본 nginx 설정 파일 교체
RUN rm /etc/nginx/conf.d/default.conf
COPY web/default.conf /etc/nginx/conf.d/

# 루트의 Vue CDN 단일 HTML 화면들
COPY intro_main.html external_index.html internal_index.html /usr/share/nginx/html/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

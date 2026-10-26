# --- build stage: compile and package with the Maven wrapper ---
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY .mvn/ .mvn/
COPY mvnw pom.xml ./
RUN chmod +x mvnw && ./mvnw -B -q dependency:go-offline
COPY src/ src/
RUN ./mvnw -B -q -DskipTests package && cp target/alert-service-*.jar /app.jar

# --- runtime stage: small JRE image, non-root user ---
FROM eclipse-temurin:21-jre
# curl is only for the compose healthcheck against /actuator/health.
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 1001 app
USER app
COPY --from=build /app.jar /app/app.jar
EXPOSE 8080
# Container-aware heap sizing so the JVM respects the compose mem_limit.
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=70 -XX:+UseSerialGC"
ENTRYPOINT ["java", "-jar", "/app/app.jar"]

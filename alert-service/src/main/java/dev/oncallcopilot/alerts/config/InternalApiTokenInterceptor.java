package dev.oncallcopilot.alerts.config;

import dev.oncallcopilot.alerts.error.UnauthorizedException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Guards the service-to-service endpoints the agent service uses to write analysis back.
 * A shared token is enough for a local demo; in a real deployment this would be mTLS or OAuth2 client credentials.
 */
public class InternalApiTokenInterceptor implements HandlerInterceptor {

	public static final String HEADER = "X-Internal-Token";

	private final byte[] expected;

	public InternalApiTokenInterceptor(String token) {
		this.expected = token.getBytes(StandardCharsets.UTF_8);
	}

	@Override
	public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
		String provided = request.getHeader(HEADER);
		// Constant-time comparison so the token can't be guessed byte-by-byte via timing.
		if (provided == null || !MessageDigest.isEqual(expected, provided.getBytes(StandardCharsets.UTF_8))) {
			throw new UnauthorizedException("Missing or invalid " + HEADER + " header");
		}
		return true;
	}

}

package dev.rootsignal.alerts.alert;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Computes a stable fingerprint for an alert so exact duplicates (same source, service and message
 * modulo volatile tokens like ids, numbers and durations) can be spotted cheaply before any AI is involved.
 */
public final class Fingerprints {

	private static final Pattern UUID = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
	private static final Pattern HEX = Pattern.compile("\\b(?:0x)?[0-9a-f]{8,}\\b");
	private static final Pattern NUMBER = Pattern.compile("\\d+(?:\\.\\d+)?");
	private static final Pattern WHITESPACE = Pattern.compile("\\s+");

	private Fingerprints() {
	}

	public static String normalizeMessage(String message) {
		String normalized = message.toLowerCase(Locale.ROOT);
		normalized = UUID.matcher(normalized).replaceAll("<id>");
		normalized = HEX.matcher(normalized).replaceAll("<id>");
		normalized = NUMBER.matcher(normalized).replaceAll("<n>");
		return WHITESPACE.matcher(normalized).replaceAll(" ").trim();
	}

	public static String of(String source, String service, String message) {
		String key = source.toLowerCase(Locale.ROOT) + '|' + service.toLowerCase(Locale.ROOT) + '|' + normalizeMessage(message);
		try {
			byte[] digest = MessageDigest.getInstance("SHA-256").digest(key.getBytes(StandardCharsets.UTF_8));
			return HexFormat.of().formatHex(digest, 0, 16);
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException("SHA-256 not available", ex);
		}
	}

}

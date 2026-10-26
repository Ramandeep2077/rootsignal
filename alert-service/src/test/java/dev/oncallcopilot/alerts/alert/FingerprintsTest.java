package dev.oncallcopilot.alerts.alert;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class FingerprintsTest {

	@Test
	void volatileTokensDoNotChangeTheFingerprint() {
		String a = Fingerprints.of("prometheus", "checkout", "Pool exhausted: 50/50 connections in use (request 7f3a9c21d4)");
		String b = Fingerprints.of("prometheus", "checkout", "Pool exhausted: 49/50 connections in use (request 0b11e2aa90)");
		assertThat(a).isEqualTo(b);
	}

	@Test
	void caseAndWhitespaceAreIgnored() {
		assertThat(Fingerprints.of("Prometheus", "Checkout", "High   LATENCY"))
				.isEqualTo(Fingerprints.of("prometheus", "checkout", "high latency"));
	}

	@Test
	void differentServicesOrMessagesProduceDifferentFingerprints() {
		String base = Fingerprints.of("prometheus", "checkout", "high latency");
		assertThat(Fingerprints.of("prometheus", "payments", "high latency")).isNotEqualTo(base);
		assertThat(Fingerprints.of("prometheus", "checkout", "disk full")).isNotEqualTo(base);
		assertThat(Fingerprints.of("datadog", "checkout", "high latency")).isNotEqualTo(base);
	}

	@Test
	void normalisesUuidsHexAndNumbers() {
		assertThat(Fingerprints.normalizeMessage("Req 123e4567-e89b-12d3-a456-426614174000 took 2.5s, id deadbeef01"))
				.isEqualTo("req <id> took <n>s, id <id>");
	}

	@Test
	void fingerprintIs32HexChars() {
		assertThat(Fingerprints.of("s", "svc", "m")).matches("[0-9a-f]{32}");
	}

}

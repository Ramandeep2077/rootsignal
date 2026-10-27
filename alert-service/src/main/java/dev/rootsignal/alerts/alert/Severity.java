package dev.rootsignal.alerts.alert;

import com.fasterxml.jackson.annotation.JsonCreator;
import java.util.Locale;

/** Normalised alert/incident severity. Ordinal order is most to least severe. */
public enum Severity {

	CRITICAL, HIGH, MEDIUM, LOW, INFO;

	/** Accepts any casing so webhook senders don't have to match ours exactly. */
	@JsonCreator
	public static Severity fromString(String value) {
		if (value == null) {
			return null;
		}
		try {
			return Severity.valueOf(value.trim().toUpperCase(Locale.ROOT));
		}
		catch (IllegalArgumentException ex) {
			throw new IllegalArgumentException("Unknown severity '" + value + "'; expected one of CRITICAL, HIGH, MEDIUM, LOW, INFO");
		}
	}

	public boolean isMoreSevereThan(Severity other) {
		return other == null || this.ordinal() < other.ordinal();
	}

}

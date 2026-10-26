package dev.oncallcopilot.alerts.error;

public class NotFoundException extends RuntimeException {

	public NotFoundException(String message) {
		super(message);
	}

}

package dev.rootsignal.alerts.error;

/** Thrown when an incident is asked to move to a status its current status doesn't allow (e.g. approving twice). */
public class InvalidStateTransitionException extends RuntimeException {

	public InvalidStateTransitionException(String message) {
		super(message);
	}

}

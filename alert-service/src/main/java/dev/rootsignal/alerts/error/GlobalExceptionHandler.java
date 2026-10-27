package dev.rootsignal.alerts.error;

import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/** Maps exceptions to RFC 9457 problem+json responses so every error has the same shape. */
@RestControllerAdvice
public class GlobalExceptionHandler {

	private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

	@ExceptionHandler(NotFoundException.class)
	ProblemDetail notFound(NotFoundException ex) {
		return problem(HttpStatus.NOT_FOUND, "Not found", ex.getMessage());
	}

	@ExceptionHandler(InvalidStateTransitionException.class)
	ProblemDetail conflict(InvalidStateTransitionException ex) {
		return problem(HttpStatus.CONFLICT, "Invalid state transition", ex.getMessage());
	}

	@ExceptionHandler(ObjectOptimisticLockingFailureException.class)
	ProblemDetail concurrentUpdate(ObjectOptimisticLockingFailureException ex) {
		return problem(HttpStatus.CONFLICT, "Concurrent update", "The incident was modified concurrently; retry.");
	}

	@ExceptionHandler(UnauthorizedException.class)
	ProblemDetail unauthorized(UnauthorizedException ex) {
		return problem(HttpStatus.UNAUTHORIZED, "Unauthorized", ex.getMessage());
	}

	@ExceptionHandler(MethodArgumentNotValidException.class)
	ProblemDetail invalidBody(MethodArgumentNotValidException ex) {
		Map<String, String> errors = new LinkedHashMap<>();
		for (FieldError error : ex.getBindingResult().getFieldErrors()) {
			errors.putIfAbsent(error.getField(), error.getDefaultMessage());
		}
		ProblemDetail problem = problem(HttpStatus.BAD_REQUEST, "Validation failed", "Request body is invalid");
		problem.setProperty("errors", errors);
		return problem;
	}

	@ExceptionHandler(HandlerMethodValidationException.class)
	ProblemDetail invalidParameters(HandlerMethodValidationException ex) {
		return problem(HttpStatus.BAD_REQUEST, "Validation failed", ex.getMessage());
	}

	@ExceptionHandler({ HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class,
			IllegalArgumentException.class })
	ProblemDetail badRequest(Exception ex) {
		return problem(HttpStatus.BAD_REQUEST, "Bad request", rootMessage(ex));
	}

	@ExceptionHandler(Exception.class)
	ProblemDetail unexpected(Exception ex) {
		log.error("Unhandled error", ex);
		return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal error", "An unexpected error occurred");
	}

	private static ProblemDetail problem(HttpStatus status, String title, String detail) {
		ProblemDetail problem = ProblemDetail.forStatusAndDetail(status, detail);
		problem.setTitle(title);
		return problem;
	}

	private static String rootMessage(Throwable ex) {
		Throwable cause = ex;
		while (cause.getCause() != null && cause.getCause() != cause) {
			cause = cause.getCause();
		}
		return cause.getMessage();
	}

}

package dev.rootsignal.alerts;

import org.springframework.boot.SpringApplication;

public class TestAlertServiceApplication {

	public static void main(String[] args) {
		SpringApplication.from(AlertServiceApplication::main).with(TestcontainersConfiguration.class).run(args);
	}

}

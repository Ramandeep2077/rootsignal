package dev.rootsignal.alerts.incident;

import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface IncidentRepository extends JpaRepository<Incident, UUID> {

	@Query("select i from Incident i where (:status is null or i.status = :status) order by i.createdAt desc")
	Page<Incident> search(@Param("status") IncidentStatus status, Pageable pageable);

}

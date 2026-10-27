package dev.rootsignal.alerts.alert;

import java.util.Collection;
import java.util.List;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AlertRepository extends JpaRepository<Alert, UUID> {

	List<Alert> findByIncidentIdOrderByTimestampAsc(UUID incidentId);

	List<Alert> findByIdIn(Collection<UUID> ids);

	long countByIncidentId(UUID incidentId);

	@Query("""
			select a from Alert a
			where (:service is null or a.service = :service)
			  and (:incidentId is null or a.incidentId = :incidentId)
			order by a.timestamp desc
			""")
	Page<Alert> search(@Param("service") String service, @Param("incidentId") UUID incidentId, Pageable pageable);

	@Query("select a.incidentId as incidentId, count(a) as alertCount from Alert a "
			+ "where a.incidentId in :incidentIds group by a.incidentId")
	List<IncidentAlertCount> countByIncidentIds(@Param("incidentIds") Collection<UUID> incidentIds);

	interface IncidentAlertCount {

		UUID getIncidentId();

		long getAlertCount();

	}

}

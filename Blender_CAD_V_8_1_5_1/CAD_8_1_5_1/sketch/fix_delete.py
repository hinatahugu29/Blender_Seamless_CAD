        elif self.action == 'DELETE_SELECTED':
            push_history(props)
            deleted = False
            
            sel_pts_list = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
            sel_lines_list = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
            
            if sel_pts_list or sel_lines_list:
                pts_to_delete = set(sel_pts_list)
                lines_to_delete = set(sel_lines_list)
                
                # Cascade 1: lines -> is_segment points, points -> lines
                changed = True
                while changed:
                    changed = False
                    # lines -> points (only is_segment points die when their lines die)
                    for l in props.sketch_lines:
                        if l.id in lines_to_delete:
                            for pid in (l.start_point_id, l.end_point_id):
                                pt = next((p for p in props.sketch_points if p.id == pid), None)
                                if pt and pt.is_segment and pid not in pts_to_delete:
                                    pts_to_delete.add(pid)
                                    changed = True
                    # points -> lines (any line connected to a deleted point must die)
                    for l in props.sketch_lines:
                        if l.id not in lines_to_delete:
                            if l.start_point_id in pts_to_delete or l.end_point_id in pts_to_delete:
                                lines_to_delete.add(l.id)
                                changed = True
                
                # Identify broken arcs/circles
                broken_arcs = set()
                for arc in props.sketch_arcs:
                    if (arc.start_point_id in pts_to_delete or 
                        arc.end_point_id in pts_to_delete or 
                        arc.mid_point_id in pts_to_delete or 
                        arc.center_point_id in pts_to_delete):
                        broken_arcs.add(arc.id)
                        
                broken_circles = set()
                for circ in props.sketch_circles:
                    if circ.center_point_id in pts_to_delete or circ.radius_point_id in pts_to_delete:
                        broken_circles.add(circ.id)
                        
                # Identify which is_segment points belong to UNBROKEN arcs
                import collections
                adj = collections.defaultdict(list)
                for l in props.sketch_lines:
                    if l.id not in lines_to_delete:
                        adj[l.start_point_id].append(l.end_point_id)
                        adj[l.end_point_id].append(l.start_point_id)
                        
                valid_segment_pts = set()
                for arc in props.sketch_arcs:
                    if arc.id not in broken_arcs:
                        stack = [(arc.start_point_id, [arc.start_point_id])]
                        visited = {arc.start_point_id}
                        path = None
                        while stack:
                            node, curr_path = stack.pop()
                            if node == arc.end_point_id:
                                path = curr_path
                                break
                            for n in adj[node]:
                                if n not in visited:
                                    pt = next((p for p in props.sketch_points if p.id == n), None)
                                    if n == arc.end_point_id or (pt and pt.is_segment):
                                        visited.add(n)
                                        stack.append((n, curr_path + [n]))
                        if path:
                            valid_segment_pts.update(path)
                        else:
                            # Path is broken, so the arc is actually broken!
                            broken_arcs.add(arc.id)
                            
                # Any is_segment point NOT in valid_segment_pts should be deleted
                for pt in props.sketch_points:
                    if pt.is_segment and pt.id not in valid_segment_pts and pt.id not in pts_to_delete:
                        pts_to_delete.add(pt.id)
                        
                # Cascade again (points -> lines)
                changed = True
                while changed:
                    changed = False
                    for l in props.sketch_lines:
                        if l.id not in lines_to_delete:
                            if l.start_point_id in pts_to_delete or l.end_point_id in pts_to_delete:
                                lines_to_delete.add(l.id)
                                changed = True
                                
                # Identify orphaned points: points that are NOT in pts_to_delete, NOT connected to any surviving line,
                # and NOT a center/radius point of a surviving circle or arc.
                # In typical CAD, explicit points remain unless deleted. But if they were implicitly created 
                # (like centers of fillets), they should be deleted if their arc is deleted.
                # Actually, in this addon, center points are explicit points. Let's not delete orphaned points 
                # unless they are in pts_to_delete. User can select and delete them.
                                
                # Apply deletions
                lines_to_keep = [{"id": l.id, "start": l.start_point_id, "end": l.end_point_id, "is_construction": getattr(l, "is_construction", False)} 
                                 for l in props.sketch_lines if l.id not in lines_to_delete]
                props.sketch_lines.clear()
                for l in lines_to_keep:
                    nl = props.sketch_lines.add()
                    nl.id = l["id"]
                    nl.start_point_id = l["start"]
                    nl.end_point_id = l["end"]
                    if l["is_construction"]:
                        nl.is_construction = True
                        
                points_to_keep = [{"id": p.id, "co": p.co[:], "is_segment": p.is_segment} 
                                  for p in props.sketch_points if p.id not in pts_to_delete]
                props.sketch_points.clear()
                for p in points_to_keep:
                    np = props.sketch_points.add()
                    np.id = p["id"]
                    np.co = p["co"]
                    np.is_segment = p["is_segment"]
                    
                arcs_to_keep = [{"id": a.id, "start": a.start_point_id, "end": a.end_point_id, 
                                 "mid": a.mid_point_id, "center": a.center_point_id, "is_construction": getattr(a, "is_construction", False)} 
                                for a in props.sketch_arcs if a.id not in broken_arcs]
                props.sketch_arcs.clear()
                for a in arcs_to_keep:
                    na = props.sketch_arcs.add()
                    na.id = a["id"]
                    na.start_point_id = a["start"]
                    na.end_point_id = a["end"]
                    na.mid_point_id = a["mid"]
                    na.center_point_id = a["center"]
                    if a["is_construction"]:
                        na.is_construction = True
                        
                circles_to_keep = [{"id": c.id, "center": c.center_point_id, "radius": c.radius_point_id, "is_construction": getattr(c, "is_construction", False)} 
                                   for c in props.sketch_circles if c.id not in broken_circles]
                props.sketch_circles.clear()
                for c in circles_to_keep:
                    nc = props.sketch_circles.add()
                    nc.id = c["id"]
                    nc.center_point_id = c["center"]
                    nc.radius_point_id = c["radius"]
                    if c["is_construction"]:
                        nc.is_construction = True
                        
                # Remove constraints involving deleted points
                constraints_to_keep = []
                for c in props.sketch_constraints:
                    keep = True
                    parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
                    for tid in parts:
                        if tid in pts_to_delete:
                            keep = False
                            break
                    if keep:
                        constraints_to_keep.append({
                            "id": c.id,
                            "type": c.type,
                            "target_ids_str": c.target_ids_str,
                            "value": c.value
                        })
                        
                props.sketch_constraints.clear()
                for c in constraints_to_keep:
                    nc = props.sketch_constraints.add()
                    nc.id = c["id"]
                    nc.type = c["type"]
                    nc.target_ids_str = c["target_ids_str"]
                    nc.value = c["value"]
                    
                props.sketch_selected_points_str = ""
                props.sketch_selected_lines_str = ""
                props.sketch_selected_point_id = -1
                props.sketch_selected_point_id_2 = -1
                props.sketch_selected_line_id = -1
                props.sketch_selected_line_id_2 = -1
                deleted = True
                self.report({'INFO'}, "Deleted selected items and cleaned up topology.")
                
            if deleted:
                solve_gcs_external(props, context)
                update_cad_preview(None, context)
            else:
                self.report({'WARNING'}, "No selection to delete.")

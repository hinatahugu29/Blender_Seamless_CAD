fn main() {
    let msg_str = r#"{"action": "solve_sketch", "points": [[1, -0.9608941078186035, 1.3110506534576416]], "constraints": [["FIXED", [1], 0.0]]}"#;
    let req: serde_json::Value = serde_json::from_str(msg_str).unwrap();
    let action = req["action"].as_str().unwrap_or("");
    
    if action == "solve_sketch" {
        let mut points_vec = Vec::new();
        if let Some(pts_arr) = req["points"].as_array() {
            for pt_val in pts_arr {
                if let Some(arr) = pt_val.as_array() {
                    if arr.len() == 3 {
                        let id = arr[0].as_u64().unwrap_or(0) as u32;
                        let x = arr[1].as_f64().unwrap_or(0.0);
                        let y = arr[2].as_f64().unwrap_or(0.0);
                        points_vec.push((id, x, y));
                    }
                }
            }
        }
        
        let mut consts_vec = Vec::new();
        if let Some(consts_arr) = req["constraints"].as_array() {
            for c_val in consts_arr {
                if let Some(arr) = c_val.as_array() {
                    if arr.len() == 3 {
                        let c_type = arr[0].as_str().unwrap_or("").to_string();
                        let target_ids: Vec<u32> = arr[1].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_u64().unwrap_or(0) as u32).collect();
                        let val = arr[2].as_f64().unwrap_or(0.0);
                        consts_vec.push((c_type, target_ids, val));
                    }
                }
            }
        }
        
        println!("points_vec: {:?}", points_vec);
        println!("consts_vec: {:?}", consts_vec);
        
        let res = seamless_core::solve_sketch(points_vec, consts_vec);
        println!("Result: {:?}", res);
    }
}

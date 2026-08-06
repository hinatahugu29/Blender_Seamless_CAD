fn main() {
    use ezpz::{solve, Config, Constraint, ConstraintRequest, IdGenerator};
    use ezpz::datatypes::inputs::DatumPoint;
    
    let mut ids = IdGenerator::default();
    let p = DatumPoint::new(&mut ids);
    
    let initial_guesses = vec![
        (p.id_x(), 10.0),
        (p.id_y(), 20.0),
    ];
    
    let requests = vec![
        ConstraintRequest::highest_priority(Constraint::Fixed(p.id_x(), 10.0)),
        ConstraintRequest::highest_priority(Constraint::Fixed(p.id_y(), 10.0)),
    ];
    
    match solve(&requests, initial_guesses, Config::default()) {
        Ok(outcome) => {
            let final_values = outcome.final_values();
            // Print out the type or structure of final_values
            println!("final_values: {:?}", final_values);
        },
        Err(e) => println!("Error: {:?}", e),
    }
}
